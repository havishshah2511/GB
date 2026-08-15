"""NLU facade: LLM first (when configured), rules always as the safety net."""
from __future__ import annotations

from typing import Any

from . import llm, rules


def extract(text: str, state: dict[str, Any], expecting: str | None = None) -> dict[str, Any]:
    """Merge both extractors. Rules win on the fields they are certain about
    (mobile, quantity units, canonical city names) because they are exact; the
    LLM fills in everything else, including messy free text."""
    rule_slots = rules.extract(text, state, expecting)

    if not llm.available():
        return rule_slots

    llm_slots = llm.extract(text, state, expecting)
    if not llm_slots:
        return rule_slots

    merged = dict(llm_slots)
    merged.update(rule_slots)  # deterministic values take precedence

    # The LLM may report an intent the rules missed, and vice versa.
    intent = rule_slots.get("message_intent") or llm_slots.get("message_intent")
    if intent:
        merged["message_intent"] = intent
    return merged


def message_intent(text: str) -> str | None:
    return rules.detect_message_intent(text)


def reply(question: str, facts: dict[str, Any], history: list[dict[str, Any]],
          next_question: str | None = None) -> str | None:
    if not llm.available():
        return None
    return llm.reply(question, facts, history, next_question)


def engine_name() -> str:
    return "claude+rules" if llm.available() else "rules"


__all__ = ["extract", "message_intent", "reply", "engine_name", "rules", "llm"]
