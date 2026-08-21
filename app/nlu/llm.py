"""Anthropic Claude adapter for slot extraction and off-script replies.

Active only when ANTHROPIC_API_KEY is set. Two hard rules enforced here:

1. The model NEVER produces prices, quantities, targets or savings. Those are
   injected as pre-computed facts and may only be echoed.
2. Extraction returns structured JSON validated against a schema built from the
   category's own slot definitions, so the model cannot invent slot names.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .. import catalog
from ..config import settings
from ..db import today

log = logging.getLogger("groupbuy.nlu.llm")

_client: Any = None
_unavailable = False

# Spec section 27.
SYSTEM_PROMPT = """You are an AI buying assistant for a group-buying platform.

Your objective is to understand exactly what the customer wants to purchase and
capture a genuine purchase intent. Keep the conversation short, friendly and
natural.

Extract information from every customer message into structured fields. Never
ask a question whose answer the customer has already provided.

Prioritize, in order:
1. Product
2. Quantity
3. Important specifications
4. Location (area and city)
5. Expected purchase date
6. Maximum waiting period
7. Product/brand flexibility
8. Name
9. Mobile number

Explain that requirements from compatible customers are combined to increase
collective buying power.

HARD RULES — these override everything else:
- Never generate, estimate, guess or imply a price, discount, saving, group
  quantity, target quantity or gap. All such numbers come from backend APIs and
  are given to you as facts. If a fact is not supplied, say you'll confirm it
  rather than inventing it.
- Never claim customers, groups or demand exist unless the supplied facts say so.
- Never describe a price as guaranteed unless the facts mark the supplier price
  as confirmed.
- Do not pressure the customer. Encourage sharing only when the facts show that
  more quantity would unlock a better price."""


def available() -> bool:
    return settings.llm_enabled and not _unavailable


def _get_client() -> Any:
    global _client, _unavailable
    if _client is not None:
        return _client
    try:
        import anthropic  # imported lazily so the app runs without the package
    except ImportError:
        log.warning("anthropic package not installed; falling back to rules NLU")
        _unavailable = True
        return None
    _client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=1,
    )
    return _client


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured outputs require every property to be listed in `required`;
    optional values are modelled as an explicit null branch instead."""
    return {"anyOf": [schema, {"type": "null"}]}


def build_schema(category: catalog.Category | None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "category": _nullable(
            {"type": "string", "enum": [c.key for c in catalog.all_categories()],
             "description": "Product category the customer is asking about."}
        ),
        "quantity": _nullable(
            {"type": "number", "description":
             "How many units the customer needs, in the category unit."}
        ),
        "city": _nullable({"type": "string", "description": "City name only."}),
        "area": _nullable({"type": "string", "description": "Neighbourhood or locality within the city."}),
        "name": _nullable({"type": "string", "description": "Customer's personal name."}),
        "mobile": _nullable({"type": "string", "description": "10-digit Indian mobile number, digits only."}),
        "desired_purchase_date": _nullable(
            {"type": "string", "format": "date",
             "description": "When the customer wants to buy, resolved to an absolute date."}
        ),
        "maximum_purchase_date": _nullable(
            {"type": "string", "format": "date",
             "description": "Latest date the customer is willing to wait until."}
        ),
        "can_wait": _nullable(
            {"type": "boolean", "description":
             "True if the customer would wait longer for a better group price."}
        ),
        "budget": _nullable({"type": "number", "description": "Budget per unit in rupees."}),
        "message_intent": _nullable(
            {"type": "string",
             "enum": ["explain", "share", "ready_to_buy", "restart", "stop", "question", "answer"],
             "description": "What the customer is doing with this message."}
        ),
    }

    if category is not None:
        for slot in category.slots:
            if slot.name in properties:
                continue
            if slot.kind == "bool":
                schema: dict[str, Any] = {"type": "boolean"}
            elif slot.kind == "number":
                schema = {"type": "number"}
            elif slot.chips and not slot.freeform:
                options = [c for c in slot.chips if "{" not in c]
                extra = [v for v in slot.synonyms if v not in options and v not in ("yes", "no")]
                schema = {"type": "string", "enum": sorted(set(options + extra))}
            else:
                schema = {"type": "string"}
            schema["description"] = f"{slot.display_label()} — {slot.question}"
            properties[slot.name] = _nullable(schema)

    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def extract(text: str, state: dict[str, Any], expecting: str | None = None) -> dict[str, Any]:
    """Return only values grounded in `text`. Empty dict on any failure."""
    client = _get_client()
    if client is None:
        return {}

    category = catalog.get(state.get("category"))
    known = {k: v for k, v in state.items() if v not in (None, "", []) and not k.startswith("_")}
    prompt = (
        f"Today is {today().isoformat()}.\n\n"
        f"Already collected (do not repeat or overwrite unless the customer corrects it):\n"
        f"{json.dumps(known, ensure_ascii=False, default=str)}\n\n"
        + (f"The assistant just asked the customer for: {expecting}\n\n" if expecting else "")
        + f"Customer's new message:\n\"\"\"{text}\"\"\"\n\n"
        "Extract only what this message states or clearly implies. Use null for "
        "anything the message does not establish. Never guess."
    )

    try:
        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": build_schema(category)},
            },
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # network, auth, rate limit, schema — all non-fatal
        log.warning("LLM extraction failed (%s); using rules extractor", exc.__class__.__name__)
        return {}

    if response.stop_reason == "refusal":
        log.info("LLM declined the extraction request")
        return {}

    raw = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("LLM returned unparseable JSON")
        return {}

    return {k: v for k, v in data.items() if v not in (None, "", [])}


# --------------------------------------------------------------------------- #
# free-form replies
# --------------------------------------------------------------------------- #
def reply(question: str, facts: dict[str, Any], history: list[dict[str, Any]],
          next_question: str | None = None) -> str | None:
    """Answer an off-script question. `facts` is the ONLY source of numbers."""
    client = _get_client()
    if client is None:
        return None

    transcript = "\n".join(
        f"{m.get('role', 'user')}: {m.get('text', '')}" for m in history[-8:]
    )
    prompt = (
        "Backend facts you may use (the ONLY numbers you are allowed to state):\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        f"Recent conversation:\n{transcript}\n\n"
        f"The customer just said:\n\"\"\"{question}\"\"\"\n\n"
        "Reply in at most three short sentences, warm and plain-spoken."
        + (f" Then ask: {next_question}" if next_question else "")
    )

    try:
        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("LLM reply failed (%s); using template reply", exc.__class__.__name__)
        return None

    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None
