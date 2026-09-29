"""Conversation orchestrator.

Owns the slot bag, decides the next question, and renders every reply. The AI
layer only extracts structured data and optionally rephrases non-numeric text --
every number in every message here comes from the pricing engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .. import catalog, i18n, nlu
from ..db import (
    dumps, execute, insert, loads, new_id, now_iso, parse_date, query_one,
    row_to_dict, today,
)
from ..utils import clean_name, money, normalise_mobile, to_float, truncate
from . import groups, intents, pricing, referrals

MAX_OPTIONAL_QUESTIONS = 2

STAGE_GREETING = "greeting"
STAGE_COLLECTING = "collecting"
STAGE_CONTACT = "contact"
STAGE_DONE = "done"


# --------------------------------------------------------------------------- #
# question model
# --------------------------------------------------------------------------- #
@dataclass
class Question:
    slot: str
    text: str
    chips: list[dict[str, str]] = field(default_factory=list)
    input_type: str = "text"       # text | tel | number | date | none
    placeholder: str = ""
    optional: bool = False

    def to_api(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "chips": self.chips,
            "input": {"type": self.input_type, "placeholder": self.placeholder},
            "optional": self.optional,
        }


def _chip(label: str, value: str | None = None) -> dict[str, str]:
    return {"label": label, "value": value if value is not None else label}


TIMING_CHIPS = [
    _chip("Immediately"), _chip("Within 3 days"), _chip("Within 7 days"),
    _chip("Within 15 days"), _chip("Within 30 days"), _chip("Choose a date"),
]
WAIT_CHIPS = [
    _chip("Yes, I can wait", "yes"),
    _chip("Maybe", "maybe"),
    _chip("No, I need it by then", "no"),
]


# --------------------------------------------------------------------------- #
# conversation storage
# --------------------------------------------------------------------------- #
def get(session_id: str) -> dict[str, Any] | None:
    return row_to_dict(query_one("SELECT * FROM conversations WHERE session_id = ?", (session_id,)))


def get_or_create(session_id: str, referral_code: str | None = None,
                  group_code: str | None = None) -> dict[str, Any]:
    existing = get(session_id)
    if existing:
        if referral_code and not existing.get("referral_code"):
            execute(
                "UPDATE conversations SET referral_code = ?, landing_group_code = ?, updated_at = ? "
                "WHERE session_id = ?",
                (referral_code, group_code, now_iso(), session_id),
            )
            referrals.record_chat_started(referral_code, session_id)
            return get(session_id)  # type: ignore[return-value]
        return existing

    stamp = now_iso()
    record = {
        "id": new_id("CNV", width=6, start=1),
        "session_id": session_id,
        "customer_id": None,
        "messages": "[]",
        "extracted_information": "{}",
        "stage": STAGE_GREETING,
        "referral_code": referral_code,
        "landing_group_code": group_code,
        "intent_id": None,
        "created_at": stamp,
        "updated_at": stamp,
    }
    insert("conversations", record)
    if referral_code:
        referrals.record_chat_started(referral_code, session_id)
    return get(session_id)  # type: ignore[return-value]


def _save(conversation: dict[str, Any], state: dict[str, Any],
          messages: list[dict[str, Any]], stage: str) -> None:
    messages = _as_seen(messages, state)
    execute(
        "UPDATE conversations SET messages = ?, extracted_information = ?, stage = ?, "
        "customer_id = ?, intent_id = ?, updated_at = ? WHERE id = ?",
        (
            dumps(messages), dumps(state), stage,
            state.get("_customer_id"), state.get("_intent_id"),
            now_iso(), conversation["id"],
        ),
    )


def _as_seen(messages: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    """The transcript records the conversation the buyer actually had.

    Some replies are translated where they are written (a sentence with values
    in it cannot be a dictionary key) and the rest at the rendering boundary.
    Storing one of those in English and the other in Hindi would leave a
    transcript in neither language, so what we keep is what they saw.

    Their own messages are never touched: those are their words, not ours.
    """
    lang = lang_of(state)
    if lang == i18n.DEFAULT:
        return messages
    return [
        i18n.localise(m, lang) if m.get("role") == "bot" else m for m in messages
    ]


def transcript(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    return loads(conversation.get("messages"), [])


def state_of(conversation: dict[str, Any]) -> dict[str, Any]:
    return loads(conversation.get("extracted_information"), {})


# --------------------------------------------------------------------------- #
# language
# --------------------------------------------------------------------------- #
def lang_of(state: dict[str, Any]) -> str:
    return state.get("lang") or i18n.DEFAULT


def language_question() -> Question | None:
    """Asked before anything else, when more than one language is offered.

    It has to be readable by someone who cannot read the other option, so the
    prompt is written in both and each chip is in its own script.
    """
    if len(i18n.LANGUAGES) < 2:
        return None
    return Question(
        slot="_lang",
        text=i18n.LANGUAGE_QUESTION,
        chips=[_chip(l["chip"], l["code"]) for l in i18n.LANGUAGES],
    )


# --------------------------------------------------------------------------- #
# opening
# --------------------------------------------------------------------------- #
def opening(conversation: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Screen 1 / screen 3 greeting."""
    state = state if state is not None else {}
    messages: list[dict[str, Any]] = []
    landing_code = conversation.get("landing_group_code")
    group = groups.get_by_code(landing_code) if landing_code else None

    if group is not None:
        referral = referrals.get_by_code(conversation.get("referral_code") or "")
        inviter = ""
        if referral and referral.get("referrer_customer_id"):
            from . import customers

            customer = customers.get(referral["referrer_customer_id"])
            first_name = (customer or {}).get("name") or ""
            inviter = first_name.split(" ")[0] if first_name else ""
        facts = pricing.price_facts(group)
        who = f"{inviter} has invited you" if inviter else "You've been invited"
        messages.append(
            {
                "role": "bot",
                "text": (
                    f"{who} to join the **{facts['group_label']}** buying group. 👋\n\n"
                    f"More buyers = better buying power. Tell us what you're looking for and "
                    f"we'll add your requirement to the pool."
                ),
            }
        )
        messages.append({"role": "bot", "card": _group_card(group, 0)})
        category = catalog.require(group["product_category"])
        product = category.spec_description(groups.spec_of(group))
        return {
            "messages": messages,
            "question": Question(
                slot="_landing_confirm",
                text=f"Are you looking for the same — **{product}** in {group['city']}?",
                chips=[
                    _chip(f"Yes, {product}", "yes"),
                    _chip("Something else", "no"),
                ],
            ),
        }
    sole = catalog.sole_category()
    if group is None and sole is not None:
        # One product on offer: asking "what are you looking to buy?" and
        # showing a single chip is a step that answers itself. Say what we do
        # and go straight to the first real question.
        state["category"] = sole.key
        state["_auto_category"] = True
        messages.append(
            {
                "role": "bot",
                "text": i18n.phrase(
                    "Hi 👋\n\nI can help you get a better price on **{product}** "
                    "by combining your order with other buyers in your city.\n\n"
                    "It takes a minute — then you can close this page and we'll message "
                    "you when the group price improves.",
                    lang_of(state),
                    product=i18n.t(sole.in_sentence(), lang_of(state)),
                ),
            }
        )
        first = next_question(state)
        if first is not None and first.text:
            messages.append({"role": "bot", "text": first.text})
        return {"messages": messages, "question": first}

    if group is None:
        messages.append(
            {
                "role": "bot",
                "text": (
                    "Hi 👋\n\nI can help you get a better price by combining your requirement "
                    "with other buyers.\n\nWhat are you looking to buy?"
                ),
            }
        )

    question = Question(
        slot="category",
        text="",
        chips=[_chip(f"{c.emoji} {c.label}", c.label) for c in catalog.all_categories()],
        placeholder="Or just type it, e.g. “I need 2 AC”",
    )
    return {"messages": messages, "question": question}


# --------------------------------------------------------------------------- #
# slot planning
# --------------------------------------------------------------------------- #
def _seed_from_group(state: dict[str, Any], group: dict[str, Any]) -> None:
    """An invitee who confirms the group inherits its product and location, so
    the link's context isn't thrown away and re-asked."""
    category = catalog.require(group["product_category"])
    spec = groups.spec_of(group)

    def fill(key: str, value: Any) -> None:
        if value not in (None, "", []) and state.get(key) in (None, "", []):
            state[key] = value

    fill("category", category.key)
    fill("city", group["city"])
    for field in category.grouping_fields:
        fill(field, category.grouping_value(spec, field))

    brand = spec.get("brand")
    if brand and category.brand_field:
        # An exact group is brand-locked, so the invitee inherits that too.
        fill(category.brand_field, brand)
        fill(category.flex_field, False)
    state["_joined_via_invite"] = group["code"]


def _slot_filled(state: dict[str, Any], name: str) -> bool:
    return state.get(name) not in (None, "", []) or name in state.get("_skipped", [])


def _brand_of(state: dict[str, Any]) -> str:
    category = catalog.get(state.get("category"))
    if category is None:
        return "That brand"
    return category.brand_of(state) or "That brand"


def _category_question(category: catalog.Category, slot: catalog.Slot,
                       state: dict[str, Any]) -> Question:
    chips = [
        _chip(chip.format(brand=_brand_of(state)), "no" if "{brand}" in chip else chip)
        if slot.kind == "bool" else _chip(chip)
        for chip in slot.chips
    ]
    if slot.kind == "bool" and chips:
        chips[0] = _chip(chips[0]["label"], "yes")
    if not slot.required and slot.kind != "bool":
        chips.append(_chip("Skip", "skip"))
    return Question(
        slot=slot.name,
        text=slot.question,
        chips=chips,
        input_type="number" if slot.kind == "number" else "text",
        optional=not slot.required,
    )


def next_question(state: dict[str, Any]) -> Question | None:
    """The single highest-priority unanswered slot. Never asks twice."""
    if not state.get("category"):
        sole = catalog.sole_category()
        if sole is None:
            return Question(
                slot="category",
                text="What are you looking to buy?",
                chips=[_chip(f"{c.emoji} {c.label}", c.label) for c in catalog.all_categories()],
            )
        # Nothing to choose between, so choose it and move on. Also covers the
        # paths that clear the requirement, like "change product".
        state["category"] = sole.key
        state["_auto_category"] = True

    category = catalog.require(state["category"])

    # For an open category "the product" is whatever they name, so ask that
    # before anything else -- "How many do you need?" is meaningless first.
    if category.open_ended and not _slot_filled(state, "product_name"):
        slot = next(s for s in category.slots if s.name == "product_name")
        return Question(
            slot="product_name",
            text=slot.question,
            placeholder="e.g. cement, LED bulbs, packaging boxes",
        )

    # The mobile number comes straight after the product so we can recognise a
    # returning buyer before putting them through the whole flow again.
    if not _slot_filled(state, "mobile"):
        # Name what they actually asked for; "Sure — something else" is nonsense.
        what = (
            str(state.get("product_name")).strip().lower()
            if category.open_ended and state.get("product_name")
            else category.label.lower()
        )
        # No echo when we picked the product for them -- "Sure — plywood 👍"
        # in reply to a message they never sent reads as a non-sequitur.
        lang = lang_of(state)
        preamble = "" if state.get("_auto_category") else i18n.phrase(
            "Sure — {product} 👍\n\n", lang, product=i18n.t(what, lang)
        )
        return Question(
            slot="mobile",
            text=preamble + i18n.t(
                "What's your mobile number?\n\n"
                "We'll use it to check if you already have a request with us, and to "
                "message you when your group price improves.",
                lang,
            ),
            input_type="tel",
            placeholder="10-digit mobile number",
        )

    optional_asked = len(state.get("_optional_asked", []))
    candidates: list[tuple[int, Question]] = []

    # Quantity competes on priority like any other question, so a category can
    # place it after its specification (plywood) or first (AC).
    if not _slot_filled(state, "quantity"):
        candidates.append(
            (category.quantity_priority, Question(
                slot="quantity",
                text=category.quantity_question,
                chips=[_chip(c) for c in category.quantity_chips],
                input_type="number",
                placeholder=i18n.phrase(
                    "Quantity in {unit}", lang_of(state),
                    unit=i18n.t(category.unit, lang_of(state)),
                ),
            ))
        )

    for slot in category.slots:
        if _slot_filled(state, slot.name) or not slot.should_ask(state):
            continue
        if not slot.required and optional_asked >= MAX_OPTIONAL_QUESTIONS:
            continue
        candidates.append((slot.priority, _category_question(category, slot, state)))

    if not _slot_filled(state, "city"):
        candidates.append(
            (45, Question(slot="city", text="Which city are you in?",
                          placeholder="e.g. Ahmedabad"))
        )
    if not _slot_filled(state, "area"):
        candidates.append(
            (46, Question(slot="area", text="Which area within the city?",
                          chips=[_chip("Skip", "skip")], optional=True,
                          placeholder="e.g. Satellite"))
        )
    if not _slot_filled(state, "desired_purchase_date"):
        candidates.append(
            (48, Question(slot="desired_purchase_date",
                          text="When are you planning to purchase?",
                          chips=TIMING_CHIPS, input_type="text"))
        )
    elif not _slot_filled(state, "can_wait"):
        candidates.append(
            (50, Question(
                slot="can_wait",
                text=("If waiting another 5-7 days could give you a better group price, "
                      "would you be comfortable waiting?"),
                chips=WAIT_CHIPS))
        )

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


# --------------------------------------------------------------------------- #
# companion products
# --------------------------------------------------------------------------- #
ADDON_DONE = "__addons_done__"


def _chosen_addons(state: dict[str, Any]) -> list[str]:
    return list(state.get("addons") or [])


def addon_question(state: dict[str, Any]) -> Question | None:
    """Offer the companion products this category usually sells alongside.

    Asked once the requirement is understood, so it reads as a helpful nudge
    rather than an upsell before we have even listened. Multi-select: each tap
    adds one and the remaining options come back, until they say they're done.
    """
    category = catalog.get(state.get("category"))
    if category is None or not category.addons or state.get("_addons_done"):
        return None

    chosen = _chosen_addons(state)
    remaining = [a for a in category.addons if a.key not in chosen]
    if not remaining:
        return None

    # The hint rides along: "Adhesive" on its own tells a buyer nothing,
    # "Fevicol, synthetic resin glue" tells them exactly what they are picking.
    lang = lang_of(state)
    # The emoji sits outside the translated label, so "🧴 Adhesive" does not
    # have to be a dictionary key in its own right.
    chips = [
        {
            **_chip(f"{a.emoji} {i18n.t(a.label, lang)}".strip(), f"addon:{a.key}"),
            **({"hint": i18n.t(a.hint, lang)} if a.hint else {}),
        }
        for a in remaining
    ]
    if chosen:
        chips.append(_chip("✅ That's everything", ADDON_DONE))
        picked = ", ".join(i18n.t(l, lang) for l in category.addon_labels(chosen))
        text = i18n.phrase(
            "Added **{picked}** 👍\n\nAnything else with it?", lang, picked=picked
        )
    else:
        chips.append(_chip("No thanks", ADDON_DONE))
        text = category.addon_prompt or (
            "Anything else you need with it? We'll ask the supplier to quote "
            "these alongside your order."
        )
    return Question(slot="_addons", text=text, chips=chips, optional=True)


#: "No thanks" at this step means "no add-ons", not "end the conversation" --
#: the same words mean something different here than anywhere else.
_ADDON_NO_MORE = re.compile(
    r"^\s*(no|no thanks|nope|nothing|none|nahi|nai|bas|bas itna|done|skip|"
    r"that'?s (it|all|everything)|i'?m good|no more)\b[\s.!]*$",
    re.I,
)


def read_addon_answer(state: dict[str, Any], text: str) -> str | None:
    """Interpret an answer at the companion-product step.

    Returns "added", "done", or None when the message is not about add-ons at
    all -- in which case the caller lets it fall through to the ordinary
    command handling, so "cancel my request" still cancels here.
    """
    category = catalog.get(state.get("category"))
    if category is None:
        return "done"

    raw = (text or "").strip()
    if raw == ADDON_DONE or _ADDON_NO_MORE.match(raw):
        return "done"

    chosen = _chosen_addons(state)
    matched = False

    if raw.startswith("addon:"):
        key = raw.split(":", 1)[1]
        if category.addon(key) and key not in chosen:
            chosen.append(key)
            matched = True
    else:
        # Typed rather than tapped: "fevicol and nails", "glue bhi chahiye".
        for addon in category.addons:
            if addon.key in chosen:
                continue
            if any(re.search(p, raw, re.I) for p in addon.synonyms):
                chosen.append(addon.key)
                matched = True

    if not matched:
        return None
    state["addons"] = chosen
    return "added"


# --------------------------------------------------------------------------- #
# companion products: their own specification, their own group
# --------------------------------------------------------------------------- #
#: Marks a question that belongs to a companion product rather than the main
#: order, so its answer is applied to that product's own slot bag.
ADDON_SLOT_PREFIX = "_ax:"


def _addon_product(main: catalog.Category | None, key: str) -> catalog.Category | None:
    """The category that knows how to specify and price one companion product."""
    addon = main.addon(key) if main else None
    if addon is None or not addon.category_key:
        return None
    return catalog.get(addon.category_key)


def _queue_addons(state: dict[str, Any]) -> None:
    """Line up the picked companion products that have questions of their own.

    "Nails" is not something a supplier can quote; 2 inch wire nails is. So a
    pick is only the start -- each one gets a couple of questions and becomes a
    requirement that pools with every other buyer wanting the same thing.
    """
    main = catalog.get(state.get("category"))
    state["_ax_queue"] = [
        key for key in _chosen_addons(state) if _addon_product(main, key) is not None
    ]


def _addon_substate(state: dict[str, Any], product: catalog.Category) -> dict[str, Any]:
    """Start the companion flow from what the buyer has already told us.

    Same person, same city, same deadline -- asking any of it a second time
    would be insulting. Only what makes this product quotable is asked.
    """
    carried = (
        "city", "area", "pincode", "name", "mobile", "can_wait", "wait_days",
        "desired_purchase_date", "maximum_purchase_date", "earliest_purchase_date",
        "purchase_within_days",
    )
    sub = {k: state[k] for k in carried if state.get(k) not in (None, "", [])}
    sub["category"] = product.key
    # The sub-flow renders its own acknowledgements, so it needs the language
    # the buyer chose; without it the companion questions come back in Hindi
    # but "Got it — 2 inch Nails" comes back in English.
    sub["lang"] = lang_of(state)
    # The thread back to the order that prompted it, so the back office can put
    # the board and the glue in front of one supplier as a single bundle.
    if state.get("_group_code"):
        sub["for_group"] = state["_group_code"]
    return sub


def _as_addon_question(question: Question) -> Question:
    return Question(
        slot=ADDON_SLOT_PREFIX + question.slot,
        text=question.text,
        chips=question.chips,
        input_type=question.input_type,
        placeholder=question.placeholder,
        optional=question.optional,
    )


def _addon_step(conversation: dict[str, Any], state: dict[str, Any],
                base_url: str) -> tuple[list[dict[str, Any]], Question | None]:
    """Advance the companion-product queue by one question.

    Returns the messages to show and the next question, or None once every
    picked product has been captured and banked.
    """
    messages: list[dict[str, Any]] = []
    # Every pass either returns a question or takes one product off the queue,
    # so the bound is the queue's length; +1 to reach the empty check.
    for _ in range(len(state.get("_ax_queue") or []) + 1):
        sub = state.get("_ax_state")
        if not sub:
            queue = list(state.get("_ax_queue") or [])
            if not queue:
                return messages, None
            key = queue.pop(0)
            state["_ax_queue"] = queue
            product = _addon_product(catalog.get(state.get("category")), key)
            if product is None:
                continue
            sub = _addon_substate(state, product)
            state["_ax_state"] = sub
            messages.append({"role": "bot", "text": _addon_opener(product, lang_of(state))})

        question = next_question(sub)
        if question is not None:
            _mark_optional_asked(sub, question)
            return messages, _as_addon_question(question)

        messages += _bank_addon(conversation, state, sub, base_url)
        state["_ax_state"] = None
    return messages, None


def _addon_opener(product: catalog.Category, lang: str) -> str:
    intro = i18n.t(product.intro, lang) or i18n.phrase(
        "Now the {product}", lang, product=i18n.t(product.in_sentence(), lang)
    )
    return intro + "\n\n" + i18n.t(
        "Just the few things a supplier will ask, so we can pool you "
        "with other buyers who need exactly the same thing.",
        lang,
    )


def _bank_addon(conversation: dict[str, Any], state: dict[str, Any],
                sub: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    """Create the companion product's own intent and show its group."""
    clean = {k: v for k, v in sub.items() if not k.startswith("_")}
    if not clean.get("desired_purchase_date"):
        clean["desired_purchase_date"] = str(today() + timedelta(days=7))
    result = intents.create(
        clean,
        conversation_id=conversation["id"],
        referral_code=conversation.get("referral_code"),
    )
    intent = result["intent"]
    group = result["group"]
    qty = float(intent["quantity"] or 0)
    facts = pricing.price_facts(group, qty)

    state["_ax_intents"] = list(state.get("_ax_intents") or []) + [intent["id"]]

    lang = lang_of(state)
    yours = i18n.t(facts["your_quantity_text"], lang)
    if result["group_created"]:
        text = i18n.phrase(
            "Saved 👍 **{yours}** of {product} — you're the first buyer in this one, "
            "so we'll pool other buyers' orders into it.",
            lang, yours=yours, product=i18n.t(intent["product"], lang),
        )
    else:
        text = i18n.phrase(
            "Even better — your **{yours}** joins buyers already asking for the same "
            "thing. That group is now at **{pooled}**.",
            lang, yours=yours, pooled=i18n.t(facts["group_quantity_text"], lang),
        )

    messages: list[dict[str, Any]] = [
        {"role": "bot", "text": text},
        {"role": "bot", "card": _group_card(group, qty)},
    ]
    if not facts.get("has_pricing"):
        messages.append({"role": "bot", "text": facts["pricing_note"]})
    return messages


def _addon_prompt(question: Question, sub: dict[str, Any]) -> str:
    """The retry wording, looked up by the product's own slot name."""
    bare = question.slot[len(ADDON_SLOT_PREFIX):]
    if not int(dict(sub.get("_misses", {})).get(bare, 0)):
        return question.text
    return CLARIFIERS.get(bare) or f"Let me put that another way 🙂 {question.text}"


def contact_question(state: dict[str, Any]) -> Question | None:
    """The mobile number is collected up front; only the name is left here."""
    if not state.get("name"):
        return Question(
            slot="name",
            text=(
                "Great. I'll combine your requirement with buyers looking for similar "
                "products in your area.\n\nWhat's your name?"
            ),
            placeholder="Your name",
        )
    return None


# --------------------------------------------------------------------------- #
# always-available commands
# --------------------------------------------------------------------------- #
#: Slots whose answer could plausibly *be* a command word, where a one-word
#: reply should be taken at face value instead ("Bye" as a name, say).
_LITERAL_SLOTS = ("name", "area", "city")


def detect_command(text: str, expecting: str | None) -> str | None:
    if expecting in _LITERAL_SLOTS and len(text.split()) <= 1:
        return None
    return nlu.rules.detect_command(text)


def _active_requests(state: dict[str, Any]) -> list[dict[str, Any]]:
    customer_id = state.get("_customer_id")
    if not customer_id:
        return []
    return intents.list_by_customer(customer_id, active_only=True)


def _reset_requirement(state: dict[str, Any]) -> dict[str, Any]:
    """Drop the product-specific answers, keep who the customer is."""
    keep = {"name", "mobile", "city", "area", "lang",
            "_customer_id", "_returning_checked"}
    return {k: v for k, v in state.items() if k in keep}


def _cancel(state: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Cancel a saved request, or abandon one that was still being collected."""
    active = _active_requests(state)
    session_intent = state.get("_intent_id")

    if session_intent and any(r["id"] == session_intent for r in active):
        record = next(r for r in active if r["id"] == session_intent)
        intents.set_status(session_intent, "cancelled")
        # The companion requirements were part of the same order -- cancelling
        # the board and leaving the glue behind would be a trap.
        for companion in state.get("_ax_intents") or []:
            if any(r["id"] == companion for r in active):
                intents.set_status(companion, "cancelled")
        return {
            "messages": [
                {
                    "role": "bot",
                    "text": (
                        f"Done — I've cancelled **{intents.summarise_for_customer(record)}** "
                        f"and taken it out of the group. 👍\n\n"
                        f"No hard feelings — you can start a new request whenever you like, and "
                        f"the group price keeps improving in the meantime."
                    ),
                }
            ],
            "state": _reset_requirement(state),
            "question": Question(
                slot="category",
                text="Anything else I can help you pool up?",
                chips=[_chip(f"{c.emoji} {c.label}", c.label) for c in catalog.all_categories()]
                + [_chip("No thanks", "exit")],
            ),
        }

    if len(active) == 1:
        record = active[0]
        intents.set_status(record["id"], "cancelled")
        return {
            "messages": [
                {
                    "role": "bot",
                    "text": (
                        f"Cancelled ✅ **{intents.summarise_for_customer(record)}** is out of "
                        f"the group now.\n\nYou're welcome back any time — pooling only works "
                        f"because people like you keep coming back."
                    ),
                }
            ],
            "state": _reset_requirement(state),
            "question": Question(
                slot="category",
                text="Want to set up something new?",
                chips=[_chip(f"{c.emoji} {c.label}", c.label) for c in catalog.all_categories()]
                + [_chip("No thanks", "exit")],
            ),
        }

    if len(active) > 1:
        chips = [
            _chip(intents.summarise_for_customer(r), f"cancel {r['id']}") for r in active[:5]
        ]
        chips.append(_chip("Keep them all", "keep"))
        return {
            "messages": [{"role": "bot", "text": "Sure — which one should I cancel?"}],
            "state": state,
            "question": Question(slot="_cancel_choice", text="", chips=chips),
        }

    # Nothing saved yet -- they are cancelling a half-finished conversation.
    return {
        "messages": [
            {
                "role": "bot",
                "text": (
                    "No problem — I hadn't saved anything yet, so there's nothing to cancel. 👍\n\n"
                    "Whenever you're ready, tell me what you're planning to buy and I'll find "
                    "you a group."
                ),
            }
        ],
        "state": _reset_requirement(state),
        "question": Question(
            slot="category",
            text="",
            chips=[_chip(f"{c.emoji} {c.label}", c.label) for c in catalog.all_categories()],
            placeholder="e.g. “I need 2 AC”",
        ),
    }


def _show_past(state: dict[str, Any], base_url: str) -> dict[str, Any]:
    from . import customers

    customer_id = state.get("_customer_id")
    # They may have given their number earlier in this chat without a customer
    # record existing yet -- resolve it rather than asking twice.
    if not customer_id and state.get("mobile"):
        known = customers.by_mobile(state["mobile"])
        if known:
            customer_id = known["id"]
            state["_customer_id"] = customer_id
        else:
            return {
                "messages": [
                    {
                        "role": "bot",
                        "text": (
                            f"I don't have anything saved against {state['mobile']} yet — "
                            f"this'll be your first one. Let's get it set up 🙂"
                        ),
                    }
                ],
                "state": state,
                "question": next_question(state),
            }

    if not customer_id:
        # We don't know who they are yet -- ask, then come straight back here.
        state["_pending_command"] = "show_past"
        return {
            "messages": [
                {"role": "bot", "text": "Happy to pull those up 👍"}
            ],
            "state": state,
            "question": Question(
                slot="mobile",
                text="What's the mobile number you used? I'll fetch everything against it.",
                input_type="tel",
                placeholder="10-digit mobile number",
            ),
        }

    records = intents.list_by_customer(customer_id, active_only=False)
    if not records:
        return {
            "messages": [
                {
                    "role": "bot",
                    "text": "I couldn't find any past requests against that number yet — "
                            "but that's easily fixed 🙂",
                }
            ],
            "state": state,
            "question": next_question(state),
        }

    _send_status_link(customer_id, base_url)
    return {
        "messages": [
            {"role": "bot", "text": "Here's everything you have with us 👇 Live status, no login needed."},
            {"role": "bot", "card": _status_card(customer_id, base_url, records)},
            {"role": "bot", "text": "I've texted you the link too, so you can reopen it any time."},
        ],
        "state": state,
        "question": None,
    }


def _change_product(state: dict[str, Any]) -> dict[str, Any]:
    cleaned = _reset_requirement(state)
    return {
        "messages": [
            {
                "role": "bot",
                "text": "Of course — let's switch it up. 🙂 I've kept your details, "
                        "so this will be quick.",
            }
        ],
        "state": cleaned,
        "question": Question(
            slot="category",
            text="What would you like to buy instead?",
            chips=[_chip(f"{c.emoji} {c.label}", c.label) for c in catalog.all_categories()],
            placeholder="Or just type it, e.g. “3 double door fridge”",
        ),
    }


def _exit(state: dict[str, Any], base_url: str) -> dict[str, Any]:
    active = _active_requests(state)
    if active:
        customer_id = state["_customer_id"]
        _send_status_link(customer_id, base_url)
        return {
            "messages": [
                {
                    "role": "bot",
                    "text": (
                        "You're all set 👍 You can close this page — you don't need to keep it "
                        "open.\n\nWe'll message you the moment more buyers join, your group hits "
                        "a new quantity level, or your price drops."
                    ),
                },
                {"role": "bot", "card": _status_card(customer_id, base_url, active)},
            ],
            "state": state,
            "question": None,
        }
    return {
        "messages": [
            {
                "role": "bot",
                "text": (
                    "No problem at all — nothing was saved. 👋\n\nCome back any time; the more "
                    "buyers pool together, the better the price gets for everyone."
                ),
            }
        ],
        "state": _reset_requirement(state),
        "question": None,
    }


def handle_command(command: str, state: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    if command == "cancel":
        return _cancel(state, base_url)
    if command == "show_past":
        return _show_past(state, base_url)
    if command == "change_product":
        return _change_product(state)
    if command == "restart":
        result = _change_product(state)
        result["messages"] = [{"role": "bot", "text": "Sure — starting fresh. 🙂"}]
        return result
    if command == "exit":
        return _exit(state, base_url)
    return None


# --------------------------------------------------------------------------- #
# returning customers
# --------------------------------------------------------------------------- #
RETURNING_CHIPS = [
    _chip("➕ Add a new request", "new"),
    _chip("📋 Show my past requests", "past"),
]


def _status_card(customer_id: str, base_url: str,
                 records: list[dict[str, Any]]) -> dict[str, Any]:
    from . import customers

    rows = []
    for record in records:
        rows.append(
            {
                "intent_id": record["id"],
                "summary": intents.summarise_for_customer(record),
                "status": record["status"],
                "strength": intents.STRENGTH_LABELS.get(
                    record["intent_strength"], record["intent_strength"]
                ),
                "group_code": record.get("group_code"),
            }
        )
    return {
        "type": "status",
        "title": "Your requests",
        "url": customers.status_url(customer_id, base_url),
        "rows": rows,
    }


def _returning_gate(state: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    """Run once, as soon as a mobile number is known.

    A number we already know short-circuits the flow: the buyer picks between a
    new request and a look at the ones they already have.
    """
    from . import customers

    mobile = state.get("mobile")
    if not mobile or state.get("_returning_checked"):
        return None
    state["_returning_checked"] = True

    customer = customers.by_mobile(mobile)
    if customer is None:
        return None

    state["_customer_id"] = customer["id"]
    # A name never changes, so carry it over and don't ask again. City and area
    # are deliberately re-asked -- a new request may be for a different place.
    if customer.get("name") and not state.get("name"):
        state["name"] = customer["name"]

    open_requests = intents.list_by_customer(customer["id"], active_only=True)
    if not open_requests:
        first = (customer.get("name") or "").split(" ")[0]
        greeting = f"Welcome back{', ' + first if first else ''} 👋"
        return {"messages": [{"role": "bot", "text": greeting}], "question": None}

    state["_open_requests"] = [r["id"] for r in open_requests]
    listing = "\n".join(f"• {intents.summarise_for_customer(r)}" for r in open_requests[:5])
    if len(open_requests) > 5:
        listing += f"\n• …and {len(open_requests) - 5} more"
    first = (customer.get("name") or "").split(" ")[0]
    count = len(open_requests)
    noun = "request" if count == 1 else "requests"

    return {
        "messages": [
            {
                "role": "bot",
                "text": (
                    f"Welcome back{', ' + first if first else ''} 👋\n\n"
                    f"You already have {count} active {noun} with us:\n\n{listing}"
                ),
            }
        ],
        "question": Question(
            slot="_returning_choice",
            text="Would you like to place a new request, or check the status of these?",
            chips=RETURNING_CHIPS,
        ),
    }


def _wants_past(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in ("past", "old", "existing", "status"):
        return True
    return bool(
        re.search(r"\b(past|previous|existing|old|status|show|check|my request)", lowered)
    ) and not re.search(r"\b(new|another|different|add|more)\b", lowered)


# --------------------------------------------------------------------------- #
# applying extracted slots
# --------------------------------------------------------------------------- #
def apply_slots(state: dict[str, Any], slots: dict[str, Any], expecting: str | None) -> list[str]:
    """Merge newly extracted slots into the state. Returns the slots that changed."""
    changed: list[str] = []
    category = catalog.get(slots.get("category") or state.get("category"))

    for key, value in slots.items():
        if key.startswith("_") or key == "message_intent":
            continue
        if value in (None, "", []):
            continue
        if key in state and state[key] == value:
            continue
        # Only the slot we asked about may overwrite an existing answer.
        if state.get(key) not in (None, "", []) and key != expecting:
            continue
        state[key] = value
        changed.append(key)

    if "quantity" in changed:
        state["quantity"] = max(0.0, to_float(state["quantity"], 0) or 0.0)
        if category and category.unit == "kg" and state["quantity"] < category.min_group_quantity:
            state["_quantity_note"] = category.min_group_quantity

    if "mobile" in changed:
        state["mobile"] = normalise_mobile(state["mobile"]) or state["mobile"]
    if "name" in changed:
        state["name"] = clean_name(state["name"]) or state["name"]

    _resolve_dates(state, changed)
    return changed


def _resolve_dates(state: dict[str, Any], changed: list[str]) -> None:
    desired = parse_date(state.get("desired_purchase_date"))
    if desired is None:
        return
    maximum = parse_date(state.get("maximum_purchase_date"))
    if "can_wait" in changed or maximum is None:
        wait_days = int(state.get("wait_days") or 0)
        if state.get("can_wait") and not wait_days:
            wait_days = 7
        maximum = desired + timedelta(days=wait_days)
    if maximum < desired:
        maximum = desired
    state["maximum_purchase_date"] = str(maximum)


def _mark_skip(state: dict[str, Any], slot: str) -> None:
    skipped = set(state.get("_skipped", []))
    skipped.add(slot)
    state["_skipped"] = sorted(skipped)


#: Slots worth re-asking until answered. Everything else is skipped after two
#: unproductive attempts so the bot can never trap the customer in a loop.
ESSENTIAL_SLOTS = ("category", "quantity", "city", "name", "mobile")


#: Shown instead of repeating a question verbatim when the answer didn't land.
#: Never a bare apology -- each one restates the question and shows the way out.
CLARIFIERS = {
    "quantity": "No worries — just the number is fine. How many do you need?",
    "city": "Almost there 🙂 Which city should I look for other buyers in?",
    "name": "What name should I save this under?",
    "mobile": ("Let's try that again — a 10-digit number, digits only. It's only used to "
               "send you price updates and to find your requests later."),
    "category": "No problem — pick one of these, or just tell me what you need:",
}

#: Offered whenever the bot has to re-ask, so the customer always has an exit.
ESCAPE_CHIPS = [
    _chip("🔁 Change product", "change product"),
    _chip("📋 My requests", "show my requests"),
    _chip("✖ Cancel", "cancel my request"),
]


def _salvage(state: dict[str, Any], expecting: str | None, text: str) -> bool:
    """Last resort after repeated misses on a free-text slot.

    The name is whatever the customer says it is -- if the parser can't make
    sense of it we take the raw text rather than asking a third time. Mobile is
    deliberately excluded: an unparseable number is useless to us and to them.
    """
    if expecting not in ("name", "area", "city"):
        return False
    if int(dict(state.get("_misses", {})).get(expecting, 0)) < 2:
        return False
    raw = truncate(text.strip(), 60)
    if not raw or nlu.rules._is_filler(raw):
        return False
    state[expecting] = raw
    misses = dict(state.get("_misses", {}))
    misses.pop(expecting, None)
    state["_misses"] = misses
    return True


def _track_misses(state: dict[str, Any], expecting: str | None, changed: list[str]) -> None:
    """Remember unproductive answers so the bot rephrases instead of repeating,
    and eventually moves on from anything optional."""
    if not expecting:
        return
    misses = dict(state.get("_misses", {}))
    if expecting in changed:
        misses.pop(expecting, None)
        state["_misses"] = misses
        return
    misses[expecting] = int(misses.get(expecting, 0)) + 1
    state["_misses"] = misses
    if expecting not in ESSENTIAL_SLOTS and misses[expecting] >= 2:
        _mark_skip(state, expecting)


def _question_text(question: Question, state: dict[str, Any]) -> str:
    misses = int(dict(state.get("_misses", {})).get(question.slot, 0))
    if not misses:
        return question.text
    clarifier = CLARIFIERS.get(question.slot)
    if clarifier:
        return clarifier
    return f"Let me put that another way 🙂 {question.text}"


def _with_escapes(question: Question | None, state: dict[str, Any]) -> Question | None:
    """After a missed answer, surface the ways out alongside the retry so the
    customer is never stuck repeating themselves."""
    if question is None:
        return None
    if not int(dict(state.get("_misses", {})).get(question.slot, 0)):
        return question
    existing = {c["value"] for c in question.chips}
    extra = [c for c in ESCAPE_CHIPS if c["value"] not in existing]
    return Question(
        slot=question.slot,
        text=question.text,
        chips=question.chips + extra,
        input_type=question.input_type,
        placeholder=question.placeholder,
        optional=question.optional,
    )


def _mark_optional_asked(state: dict[str, Any], question: Question | None) -> None:
    if question is None or not question.optional:
        return
    asked = set(state.get("_optional_asked", []))
    asked.add(question.slot)
    state["_optional_asked"] = sorted(asked)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def _group_card(group: dict[str, Any], customer_qty: float) -> dict[str, Any]:
    facts = pricing.price_facts(group, customer_qty)
    return {"type": "group", **facts}


def _next_target_card(group: dict[str, Any], customer_qty: float) -> dict[str, Any] | None:
    facts = pricing.price_facts(group, customer_qty)
    if not facts.get("next_target_qty"):
        return None
    return {"type": "next_target", **facts}


def _share_card(group: dict[str, Any], customer_id: str, base_url: str,
                customer_qty: float) -> dict[str, Any]:
    referral = referrals.ensure(customer_id, group["id"])
    facts = pricing.price_facts(group, customer_qty)
    kit = referrals.share_kit(group, facts, referral["referral_code"], base_url)
    return {"type": "share", **kit}


def acknowledgement(state: dict[str, Any], changed: list[str]) -> str | None:
    """Short confirmation so the customer sees they were understood."""
    category = catalog.get(state.get("category"))
    if category is None:
        return None
    # Only echo back the product-defining answers; confirming every yes/no
    # would make the conversation twice as long for no benefit.
    interesting = {"quantity", *category.grouping_fields}
    if category.brand_field:
        interesting.add(category.brand_field)
    if not interesting.intersection(changed):
        return None
    lang = lang_of(state)
    qty = to_float(state.get("quantity"), 0) or 0
    spec = category.spec_description(state)
    # Before any spec is known this is just the bare noun ("AC"), which would
    # read as "2 ACs of AC".
    if spec.strip() == category.noun():
        spec = ""
    spec = i18n.t(spec, lang)
    if qty and spec:
        # "2 × 1.5 Ton Split Inverter AC" rather than "2 ACs of 1.5 Ton ... AC".
        counter = (
            i18n.phrase("{qty} kg of", lang, qty=f"{qty:g}")
            if category.unit == "kg" else f"{qty:g} ×"
        )
        return i18n.phrase("Got it — {counter} {spec}.", lang, counter=counter, spec=spec)
    if qty:
        return i18n.phrase(
            "Got it — {what}.", lang,
            what=i18n.t(category.qty_label(qty, state.get("unit")), lang),
        )
    if spec:
        return i18n.phrase("Got it — {what}.", lang, what=spec)
    return None


def summary(state: dict[str, Any]) -> dict[str, Any]:
    """Public view of what has been collected (drives the UI's progress strip)."""
    category = catalog.get(state.get("category"))
    return {
        "category": state.get("category"),
        "category_label": category.label if category else None,
        "product": category.spec_description(state) if category else None,
        "quantity": state.get("quantity"),
        "quantity_text": category.qty_label(to_float(state.get("quantity"), 0) or 0, state.get("unit"))
        if category and state.get("quantity") else None,
        "city": state.get("city"),
        "area": state.get("area"),
        "desired_purchase_date": state.get("desired_purchase_date"),
        "maximum_purchase_date": state.get("maximum_purchase_date"),
        "can_wait": state.get("can_wait"),
        "name": state.get("name"),
        "mobile": state.get("mobile"),
        "intent_id": state.get("_intent_id"),
        "group_code": state.get("_group_code"),
    }


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
def handle(session_id: str, text: str = "", referral_code: str | None = None,
           group_code: str | None = None, base_url: str = "") -> dict[str, Any]:
    conversation = get_or_create(session_id, referral_code, group_code)
    state = state_of(conversation)
    history = transcript(conversation)
    stage = conversation["stage"]
    messages: list[dict[str, Any]] = []

    # --- first contact: which language? ------------------------------------ #
    # Before the greeting, because the greeting itself has to be in it.
    if stage == STAGE_GREETING and not text.strip():
        question = language_question()
        if question is not None:
            messages.append({"role": "bot", "text": question.text})
            history += messages
            state["_expecting"] = question.slot
            _save(conversation, state, history, STAGE_COLLECTING)
            return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

    # --- first contact: greet, ask nothing else ---------------------------- #
    if stage == STAGE_GREETING and not text.strip():
        intro = opening(conversation, state)
        messages = intro["messages"]
        question = intro["question"]
        history += messages
        state["_expecting"] = question.slot if question else None
        _save(conversation, state, history, STAGE_COLLECTING)
        return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

    # --- resume: the customer reloaded or came back later ------------------ #
    if not text.strip():
        question = _current_question(state, stage)
        payload = _respond(session_id, stage, history, question, state, base_url)
        payload["resumed"] = True
        return payload

    history.append({"role": "user", "text": truncate(text, 500), "ts": now_iso()})
    expecting = state.get("_expecting")

    # --- the language they picked ------------------------------------------ #
    # Answered before we have greeted them, so the greeting itself lands in it.
    if expecting == "_lang":
        picked = i18n.language_of(text)
        state["lang"] = picked or i18n.DEFAULT
        intro = opening(conversation, state)
        question = intro["question"]
        state["_expecting"] = question.slot if question else None

        if picked is not None:
            messages += intro["messages"]
            history += messages
            _save(conversation, state, history, STAGE_COLLECTING)
            return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

        # Not a language at all -- they have skipped past it and started
        # telling us what they need. Greet them in English and read the message
        # in this same turn: throwing away the first thing someone says to us
        # is a worse failure than not knowing their language.
        asked = question.text if question else None
        messages += [m for m in intro["messages"] if m.get("text") != asked]
        expecting = state["_expecting"]

    # --- steering commands win over everything, at every stage -------------- #
    # "cancel my request" is never an answer to "Split or Window?".
    if expecting == "_cancel_choice":
        chosen = re.search(r"\b(INT-\d+)\b", text, re.I)
        if chosen:
            intent_id = chosen.group(1).upper()
            record = intents.get_full(intent_id)
            intents.set_status(intent_id, "cancelled")
            label = intents.summarise_for_customer(record) if record else intent_id
            messages.append(
                {"role": "bot", "text": f"Cancelled ✅ **{label}** is out of the group now."}
            )
        else:
            messages.append({"role": "bot", "text": "Kept them all 👍 Nothing was cancelled."})
        state["_expecting"] = None
        remaining = _active_requests(state)
        history += messages
        _save(conversation, state, history, STAGE_DONE if remaining else STAGE_COLLECTING)
        payload = _respond(
            session_id, STAGE_DONE if remaining else STAGE_COLLECTING,
            messages, None, state, base_url,
        )
        payload["chips"] = [
            _chip("➕ New request", "new request"),
            _chip("📋 My requests", "show my requests"),
        ]
        return payload

    # --- picking companion products ---------------------------------------- #
    # Ahead of the command handler: at this step "no thanks" means "no add-ons",
    # not "end the chat". Anything that isn't about add-ons falls through, so
    # "cancel my request" still cancels here.
    if expecting == "_addons":
        answer = read_addon_answer(state, text)
        if answer is not None:
            if answer == "done":
                state["_addons_done"] = True
            question = addon_question(state)
            if question is not None:
                state["_expecting"] = question.slot
                messages.append({"role": "bot", "text": question.text})
                history += messages
                _save(conversation, state, history, STAGE_CONTACT)
                return _respond(session_id, STAGE_CONTACT, messages, question, state, base_url)

            state["_addons_done"] = True
            more, question, state = complete(conversation, state, base_url)
            messages += more
            return _finish_turn(session_id, conversation, state, history, messages,
                                question, base_url)

    command = detect_command(text, expecting)
    if command:
        outcome = handle_command(command, state, base_url)
        if outcome is not None:
            state = outcome["state"]
            messages += outcome["messages"]
            question = outcome["question"]
            state["_expecting"] = question.slot if question else None
            if question is not None and question.text:
                messages.append({"role": "bot", "text": question.text})
            stage = STAGE_DONE if question is None else STAGE_COLLECTING
            history += messages
            _save(conversation, state, history, stage)
            payload = _respond(session_id, stage, messages, question, state, base_url)
            if question is None and not payload.get("chips"):
                payload["chips"] = [
                    _chip("➕ New request", "new request"),
                    _chip("📋 My requests", "show my requests"),
                ]
            return payload

    # --- specifying a companion product ------------------------------------- #
    # The main order is already banked; these answers build a requirement of
    # its own, in its own slot bag, which becomes its own group.
    if expecting and expecting.startswith(ADDON_SLOT_PREFIX):
        slot_name = expecting[len(ADDON_SLOT_PREFIX):]
        sub = state.get("_ax_state") or {}
        public = {k: v for k, v in sub.items() if not k.startswith("_")}
        slots = nlu.extract(text, public, slot_name)
        slots.pop("message_intent", None)
        if text.strip().lower() in ("skip", "no preference", "not sure", "none"):
            _mark_skip(sub, slot_name)
        changed = apply_slots(sub, slots, slot_name)
        _track_misses(sub, slot_name, changed)
        state["_ax_state"] = sub

        note = acknowledgement(sub, changed)
        if note:
            messages.append({"role": "bot", "text": note})

        more, question = _addon_step(conversation, state, base_url)
        messages += more
        return _finish_turn(session_id, conversation, state, history, messages,
                            question, base_url)

    # --- invitee confirming the group they were invited to ------------------ #
    if expecting == "_landing_confirm":
        group = groups.get_by_code(conversation.get("landing_group_code") or "")
        wants_same = nlu.rules.extract_bool(text)
        if re.search(r"something else|different|other product|not that", text, re.I):
            wants_same = False

        # The reply may carry real content ("yes, I need 2") -- read it first so
        # the group's spec only fills what the customer didn't say themselves.
        public = {k: v for k, v in state.items() if not k.startswith("_")}
        apply_slots(state, nlu.extract(text, public), None)

        if group is not None and wants_same is not False:
            _seed_from_group(state, group)
            messages.append({"role": "bot", "text": "Perfect — I'll add you to that group."})
        else:
            messages.append({"role": "bot", "text": "No problem — what are you looking to buy?"})

        question = next_question(state)
        state["_expecting"] = question.slot if question else None
        if question is not None and question.text:
            messages.append({"role": "bot", "text": question.text})
        history += messages
        _save(conversation, state, history, STAGE_COLLECTING)
        return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

    # --- returning buyer choosing between a new request and their old ones -- #
    if expecting == "_returning_choice":
        if _wants_past(text):
            customer_id = state.get("_customer_id")
            records = intents.list_by_customer(customer_id, active_only=True) if customer_id else []
            messages.append(
                {
                    "role": "bot",
                    "text": (
                        "Here's everything you have with us 👇 The link below always shows "
                        "the live status of each request — no login needed."
                    ),
                }
            )
            messages.append({"role": "bot", "card": _status_card(customer_id, base_url, records)})
            _send_status_link(customer_id, base_url)
            messages.append(
                {
                    "role": "bot",
                    "text": "I've also sent that link to your mobile so you can reopen it any time.",
                }
            )
            state["_expecting"] = None
            state["_showed_status"] = True
            history += messages
            _save(conversation, state, history, STAGE_COLLECTING)
            payload = _respond(session_id, STAGE_COLLECTING, messages, None, state, base_url)
            payload["chips"] = [_chip("➕ Add a new request", "new request")]
            payload["input"] = {"type": "text", "placeholder": "Tell me what else you need…"}
            return payload

        messages.append({"role": "bot", "text": "Sure — let's set up a new request. 👍"})
        state.pop("_showed_status", None)
        question = next_question(state)
        state["_expecting"] = question.slot if question else None
        if question is not None and question.text:
            messages.append({"role": "bot", "text": question.text})
        history += messages
        _save(conversation, state, history, STAGE_COLLECTING)
        return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

    # --- understand -------------------------------------------------------- #
    slots = nlu.extract(text, {k: v for k, v in state.items() if not k.startswith("_")}, expecting)
    intent = slots.pop("message_intent", None)

    if expecting and text.strip().lower() in ("skip", "no preference", "not sure", "none"):
        _mark_skip(state, expecting)

    changed = apply_slots(state, slots, expecting)
    _track_misses(state, expecting, changed)
    if expecting and expecting not in changed and _salvage(state, expecting, text):
        changed.append(expecting)

    # "Choose a date" opens a date picker instead of another text round-trip.
    if expecting == "desired_purchase_date" and "choose a date" in text.lower():
        question = Question(
            slot="desired_purchase_date",
            text="Sure — pick your planned purchase date:",
            input_type="date",
        )
        state["_expecting"] = question.slot
        messages.append({"role": "bot", "text": question.text})
        history += messages
        _save(conversation, state, history, STAGE_COLLECTING)
        return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

    # --- conversational side-tracks ---------------------------------------- #
    # cancel / show_past / change_product / restart / exit are handled above,
    # before extraction, so they work at any point in the flow.
    if intent == "explain":
        messages.append({"role": "bot", "text": _explainer(state)})

    if intent == "ready_to_buy" and state.get("_intent_id"):
        intents.set_strength(state["_intent_id"], "ready_to_buy")
        messages.append(
            {"role": "bot", "text": "Noted 👍 I've marked you as ready to buy at the group price. "
                                    "We'll contact you as soon as the supplier quote is confirmed."}
        )

    if intent == "share" and state.get("_group_code") and state.get("_customer_id"):
        group = groups.get_by_code(state["_group_code"])
        if group:
            messages.append({"role": "bot", "text": "Here's your invite link 👇"})
            messages.append(
                {"role": "bot",
                 "card": _share_card(group, state["_customer_id"], base_url,
                                     to_float(state.get("quantity"), 0) or 0)}
            )
        history += messages
        _save(conversation, state, history, stage)
        return _respond(session_id, stage, messages, None, state, base_url)

    # --- acknowledge ------------------------------------------------------- #
    if stage != STAGE_DONE:
        note = acknowledgement(state, changed)
        if note:
            messages.append({"role": "bot", "text": note})
        if state.pop("_quantity_note", None):
            category = catalog.require(state["category"])
            messages.append(
                {"role": "bot",
                 "text": f"Heads up: groups for {category.label.lower()} usually start around "
                         f"{category.qty_label(category.min_group_quantity)}. Smaller requirements "
                         f"still count — they just take a little longer to pool."}
            )

    # --- decide what happens next ------------------------------------------ #
    if stage == STAGE_DONE:
        question = None
        if not messages:
            messages.append({"role": "bot", "text": _post_completion_reply(state, base_url)})
        history += messages
        _save(conversation, state, history, STAGE_DONE)
        return _respond(session_id, STAGE_DONE, messages, None, state, base_url)

    # A known mobile number interrupts the flow exactly once.
    gate = _returning_gate(state, base_url)

    # They asked to see their requests before we knew who they were; the mobile
    # has now landed, so answer the original question instead of the gate's.
    if state.pop("_pending_command", None) == "show_past":
        outcome = _show_past(state, base_url)
        state = outcome["state"]
        messages += outcome["messages"]
        question = outcome["question"]
        state["_expecting"] = question.slot if question else None
        if question is not None and question.text:
            messages.append({"role": "bot", "text": question.text})
        stage = STAGE_DONE if question is None else STAGE_COLLECTING
        history += messages
        _save(conversation, state, history, stage)
        payload = _respond(session_id, stage, messages, question, state, base_url)
        if question is None:
            payload["chips"] = [
                _chip("➕ New request", "new request"),
                _chip("📋 Open my requests", "show my requests"),
            ]
        return payload

    if gate is not None:
        messages += gate["messages"]
        if gate["question"] is not None:
            question = gate["question"]
            state["_expecting"] = question.slot
            messages.append({"role": "bot", "text": question.text})
            history += messages
            _save(conversation, state, history, STAGE_COLLECTING)
            return _respond(session_id, STAGE_COLLECTING, messages, question, state, base_url)

    question = next_question(state)
    stage = STAGE_COLLECTING

    if question is None:
        stage = STAGE_CONTACT
        question = contact_question(state)

    # Companion products come last: offer them once we understand the order.
    if question is None:
        question = addon_question(state)

    if question is None:
        # Everything collected -> create the intent and show the group.
        more, question, state = complete(conversation, state, base_url)
        messages += more
        return _finish_turn(session_id, conversation, state, history, messages,
                            question, base_url)

    _mark_optional_asked(state, question)
    state["_expecting"] = question.slot
    prompt = _question_text(question, state)
    question = _with_escapes(question, state)
    if prompt:
        messages.append({"role": "bot", "text": prompt})
    history += messages
    _save(conversation, state, history, stage)
    return _respond(session_id, stage, messages, question, state, base_url)


def _finish_turn(session_id: str, conversation: dict[str, Any], state: dict[str, Any],
                 history: list[dict[str, Any]], messages: list[dict[str, Any]],
                 question: Question | None, base_url: str) -> dict[str, Any]:
    """Close a turn that either asked a companion question or ended the chat."""
    if question is None:
        # The sign-off is held back while companion products are still being
        # specified, so it lands here, once, at the real end.
        if not state.get("_signed_off"):
            messages += _closing_messages(state, base_url)
        state["_expecting"] = None
        history += messages
        _save(conversation, state, history, STAGE_DONE)
        return _respond(session_id, STAGE_DONE, messages, None, state, base_url)

    state["_expecting"] = question.slot
    prompt = _addon_prompt(question, state.get("_ax_state") or {})
    if prompt:
        messages.append({"role": "bot", "text": prompt})
    history += messages
    _save(conversation, state, history, STAGE_CONTACT)
    return _respond(session_id, STAGE_CONTACT, messages, question, state, base_url)


def _current_question(state: dict[str, Any], stage: str) -> Question | None:
    if stage == STAGE_DONE:
        return None
    # Reloaded before answering it: ask again rather than dropping into the
    # flow in whatever language we happened to default to.
    if state.get("_expecting") == "_lang":
        return language_question()
    # Mid-way through a companion product: resume its question, not the main
    # order's, which is already complete.
    sub = state.get("_ax_state")
    if sub:
        question = next_question(sub)
        if question is not None:
            return _as_addon_question(question)
    return next_question(state) or contact_question(state) or addon_question(state)


def _respond(session_id: str, stage: str, messages: list[dict[str, Any]],
             question: Question | None, state: dict[str, Any], base_url: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "stage": stage,
        "messages": messages,
        "summary": summary(state),
        "engine": nlu.engine_name(),
        "done": stage == STAGE_DONE,
    }
    if question is not None:
        payload["question"] = question.to_api()
        payload["chips"] = question.chips
        payload["input"] = {
            "type": question.input_type,
            # The page's own fallback placeholder is English, so send one
            # rather than let it show through a Hindi conversation.
            "placeholder": question.placeholder or "Type your message…",
        }
    else:
        payload["chips"] = _done_chips(state)
        payload["input"] = {"type": "text", "placeholder": "Ask me anything…"}
    # One place, at the very edge: everything the buyer reads is translated,
    # and every value the server will read back is left exactly as written.
    # The transcript stays in English, so the back office reads one language.
    return i18n.localise(payload, lang_of(state))


def _done_chips(state: dict[str, Any]) -> list[dict[str, str]]:
    if not state.get("_group_code"):
        return []
    return [
        _chip("📲 Share on WhatsApp", "share"),
        _chip("🛒 I'm ready to buy", "I am ready to buy"),
        _chip("📋 My requests", "show my requests"),
        _chip("➕ Another product", "change product"),
        _chip("✖ Cancel request", "cancel my request"),
    ]


# --------------------------------------------------------------------------- #
# completion
# --------------------------------------------------------------------------- #
def finalise(conversation: dict[str, Any], state: dict[str, Any],
             base_url: str = "", closing: bool = True) -> dict[str, Any]:
    """Create the purchase intent, join a group, and render sections 12-17.

    `closing` holds back the sign-off when companion products still have
    questions of their own -- "you're done" belongs at the end of the
    conversation, not in the middle of it.
    """
    clean = {k: v for k, v in state.items() if not k.startswith("_")}
    if not clean.get("desired_purchase_date"):
        clean["desired_purchase_date"] = str(today() + timedelta(days=7))
    result = intents.create(
        clean,
        conversation_id=conversation["id"],
        referral_code=conversation.get("referral_code"),
    )

    intent = result["intent"]
    customer = result["customer"]
    group = result["group"]
    qty = float(intent["quantity"] or 0)
    facts = pricing.price_facts(group, qty)
    category = catalog.require(group["product_category"])

    state["_intent_id"] = intent["id"]
    state["_customer_id"] = customer["id"]
    state["_group_code"] = group["code"]
    # Baseline for live updates: anything above this while the chat stays open
    # is another buyer merging in.
    state["_live_snapshot"] = _snapshot(facts)

    messages: list[dict[str, Any]] = []

    lang = lang_of(state)
    yours = i18n.t(facts["your_quantity_text"], lang)
    if result["group_created"]:
        opener = i18n.phrase(
            "You're the first buyer in a new **{group}** group 🚀\n\n"
            "Your {yours} is now the starting quantity.",
            lang, group=facts["group_label"], yours=yours,
        )
        opener += " " + i18n.t(
            "As more buyers with matching requirements join, we'll take the pooled "
            "quantity to suppliers and get you a group price."
            if not facts.get("has_pricing")
            else "As more buyers with matching requirements join, the price drops for everyone.",
            lang,
        )
        messages.append({"role": "bot", "text": opener})
    else:
        messages.append(
            {
                "role": "bot",
                "text": i18n.phrase(
                    "Good news 🎉\n\nYour {yours} requirement can be combined with other "
                    "buyers. There are now approximately **{pooled}** in this buying group.",
                    lang, yours=yours,
                    pooled=i18n.t(facts["group_quantity_text"], lang),
                ),
            }
        )

    messages.append({"role": "bot", "card": _group_card(group, qty)})

    # A product nobody has quoted for yet: say so instead of implying a price.
    if not facts.get("has_pricing"):
        messages.append({"role": "bot", "text": facts["pricing_note"]})

    # Anything else the category wants to tell them (solar's subsidy estimate).
    if category.extra_cards:
        for card in category.extra_cards(state, facts):
            messages.append({"role": "bot", "card": card})

    target_card = _next_target_card(group, qty)
    if target_card:
        messages.append(
            {
                "role": "bot",
                "text": i18n.phrase(
                    "There's another opportunity 👇 We're only **{gap}** away from "
                    "the next price level.",
                    lang, gap=i18n.t(facts["gap_text"], lang),
                ),
            }
        )
        messages.append({"role": "bot", "card": target_card})
        messages.append(
            {
                "role": "bot",
                "text": i18n.phrase(
                    "Know someone planning to buy {product}? Invite them to this group. "
                    "If their requirement joins, the total quantity increases and "
                    "**your price can also become lower.**",
                    lang, product=i18n.t(category.label.lower(), lang),
                ),
            }
        )
        messages.append({"role": "bot", "card": _share_card(group, customer["id"], base_url, qty)})

    # Confirm the basket, without pricing it -- nobody has quoted for these.
    picked = category.addon_labels(_chosen_addons(state))
    if picked:
        pending = bool(state.get("_ax_queue"))
        note = (
            i18n.t(
                "Each of these gets its own buying group too, so we can ask a "
                "supplier to quote them for the whole pool. A few quick "
                "questions on each and you're done.",
                lang,
            )
            if pending else
            i18n.phrase(
                "We'll ask the supplier to quote these alongside the {product}, so the "
                "group rate applies to them too. Prices come once the quote is in.",
                lang, product=i18n.t(category.in_sentence(), lang),
            )
        )
        messages.append(
            {
                "role": "bot",
                "card": {
                    "type": "addons",
                    "title": "Also in your request",
                    "items": picked,
                    "note": note,
                },
            }
        )

    if closing:
        messages += _closing_messages(state, base_url)

    return {"messages": messages, "state": state, "intent": intent, "group": group}


def _closing_messages(state: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    """The sign-off: what happens next, and the link back in.

    The buyer has no account, so the status link is how they return.
    """
    state["_signed_off"] = True
    messages: list[dict[str, Any]] = [{"role": "bot", "card": _done_card(state)}]
    customer_id = state.get("_customer_id")
    if customer_id:
        records = intents.list_by_customer(customer_id, active_only=True)
        messages.append({"role": "bot", "card": _status_card(customer_id, base_url, records)})
        _send_status_link(customer_id, base_url)
    return messages


def complete(conversation: dict[str, Any], state: dict[str, Any],
             base_url: str) -> tuple[list[dict[str, Any]], Question | None, dict[str, Any]]:
    """Bank the requirement, then ask each companion product's own questions.

    The main order is saved first and on its own: whatever happens next, the
    thing they came for is recorded. Only then do we ask what kind of nails.
    """
    _queue_addons(state)
    pending = bool(state.get("_ax_queue"))
    result = finalise(conversation, state, base_url, closing=not pending)
    messages = list(result["messages"])
    state = result["state"]

    more, question = _addon_step(conversation, state, base_url)
    messages += more
    return messages, question, state


def _done_card(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "done",
        "title": "You're done 👍",
        "subtitle": "You don't need to keep checking this page. We'll message you when:",
        "bullets": [
            "More buyers join your group",
            "Your group reaches a new quantity level",
            "Your price drops",
            "The final purchase opportunity becomes available",
        ],
        "footer": "Want a better price sooner? Share your group with someone who may also be interested.",
    }


def _post_completion_reply(state: dict[str, Any], base_url: str) -> str:
    group = groups.get_by_code(state.get("_group_code") or "")
    if group is None:
        return "You're all set 👍 We'll message you as soon as there's news about your group."
    facts = pricing.price_facts(group, to_float(state.get("quantity"), 0) or 0)
    answer = nlu.reply(
        "The customer sent another message after completing their requirement.",
        facts,
        [],
        next_question=None,
    )
    if answer:
        return answer
    lines = [
        f"Your group is at **{facts['group_quantity_text']}** and the current group price is "
        f"**{facts['current_price_text']}**."
    ]
    if facts.get("next_target_qty"):
        lines.append(
            f"Just {facts['gap_text']} more and it drops to {facts['next_price_text']}."
        )
    lines.append("We'll message you the moment anything changes.")
    return "\n\n".join(lines)


def _send_status_link(customer_id: str | None, base_url: str) -> None:
    """Text the buyer their 'my requests' link so they can leave the page."""
    from . import customers, notifications

    if not customer_id:
        return
    url = customers.status_url(customer_id, base_url)
    notifications.queue(
        customer_id, None, "status_link",
        "Here are your group-buying requests and their live status 👇\n" + url,
        payload={"url": url},
        dedupe_key=f"status_link:{customer_id}:{today()}",
    )


# --------------------------------------------------------------------------- #
# live updates -- another buyer merging into the group while this chat is open
# --------------------------------------------------------------------------- #
def _snapshot(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "qty": float(facts.get("group_quantity") or 0),
        "price": float(facts.get("current_price") or 0),
    }


def live_updates(session_id: str, base_url: str = "") -> dict[str, Any]:
    """Poll hook for an open chat window.

    Compares the group as it stands now against the snapshot taken when the
    customer last saw it, and narrates the difference. Every figure comes from
    the pricing engine -- this only decides which template to use.
    """
    conversation = get(session_id)
    empty = {"session_id": session_id, "messages": [], "changed": False}
    if conversation is None:
        return empty

    state = state_of(conversation)
    code = state.get("_group_code")
    if not code:
        return empty
    group = groups.get_by_code(code)
    if group is None:
        return empty

    qty = to_float(state.get("quantity"), 0) or 0.0
    facts = pricing.price_facts(group, qty)
    current = _snapshot(facts)
    previous = state.get("_live_snapshot")

    if not previous:
        state["_live_snapshot"] = current
        _save(conversation, state, transcript(conversation), conversation["stage"])
        return empty

    grew = current["qty"] > float(previous.get("qty") or 0)
    cheaper = 0 < current["price"] < float(previous.get("price") or 0)
    if not grew and not cheaper:
        if current != previous:      # quantity fell (expiry) -- update quietly
            state["_live_snapshot"] = current
            _save(conversation, state, transcript(conversation), conversation["stage"])
        return empty

    category = catalog.require(group["product_category"])
    added = current["qty"] - float(previous.get("qty") or 0)
    messages: list[dict[str, Any]] = []

    if cheaper:
        messages.append(
            {
                "role": "bot",
                "text": (
                    f"🎉 **Price drop — right now!**\n\nMore buyers just joined your group, "
                    f"so it moved from {money(previous['price'])} to "
                    f"**{facts['current_price_text']}** per {category.unit}."
                ),
            }
        )
    else:
        who = f"**{category.qty_label(added, facts.get('unit'))}**" if added > 0 else "A new requirement"
        messages.append(
            {
                "role": "bot",
                "text": (
                    f"👥 A matching requirement just merged into your group — {who} added.\n\n"
                    f"Your group is now at **{facts['group_quantity_text']}**."
                ),
            }
        )

    messages.append({"role": "bot", "card": _group_card(group, qty)})
    target = _next_target_card(group, qty)
    if target:
        messages.append({"role": "bot", "card": target})
    if state.get("_customer_id"):
        messages.append(
            {"role": "bot", "card": _share_card(group, state["_customer_id"], base_url, qty)}
        )

    state["_live_snapshot"] = current
    history = transcript(conversation)
    for message in messages:
        history.append({**message, "ts": now_iso(), "live": True})
    _save(conversation, state, history, conversation["stage"])

    return {
        "session_id": session_id,
        "messages": messages,
        "changed": True,
        "summary": summary(state),
    }


def _explainer(state: dict[str, Any]) -> str:
    return (
        "It's simple: we collect requirements from buyers who want the same thing in the same "
        "city, then negotiate as one large order.\n\n"
        "**More quantity → better price for everyone.**\n\n"
        "You tell us once what you need and by when. We do the rest and message you whenever "
        "your group's position improves. There's no charge for joining, and nothing is "
        "confirmed until you approve the final offer."
    )
