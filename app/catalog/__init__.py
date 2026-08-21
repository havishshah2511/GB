"""Category registry.

To add a category: create a module next to this one that exposes `CATEGORY`
(a `Category` instance) and add it to `_MODULES`. Nothing else in the codebase
needs to change.
"""
from __future__ import annotations

import importlib
import re
from typing import Any

from .base import Category, Slab, Slot

#: Order matters: it is the order of the opening chips, and the open-ended
#: fallback must come last.
_MODULES = ("ac", "refrigerator", "general")

CATEGORIES: dict[str, Category] = {}
for _name in _MODULES:
    _cat = importlib.import_module(f"{__name__}.{_name}").CATEGORY
    CATEGORIES[_cat.key] = _cat

#: The category used when a product matches no specific one.
FALLBACK_KEY = next((c.key for c in CATEGORIES.values() if c.open_ended), None)

_TRIGGERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.I), cat.key)
    for cat in CATEGORIES.values()
    for pattern in cat.triggers
]
_EXCLUSIONS: dict[str, list[re.Pattern[str]]] = {
    cat.key: [re.compile(p, re.I) for p in cat.exclusions]
    for cat in CATEGORIES.values()
}


def get(key: str | None) -> Category | None:
    if not key:
        return None
    return CATEGORIES.get(str(key).strip().upper())


def require(key: str | None) -> Category:
    category = get(key)
    if category is None:
        raise KeyError(f"Unknown product category: {key!r}")
    return category


def all_categories() -> list[Category]:
    return list(CATEGORIES.values())


def detect(text: str, allow_fallback: bool = False) -> str | None:
    """Route free text to a category key.

    `allow_fallback` returns the open-ended category for anything that names a
    product we have no dedicated flow for. It is off by default so that a
    greeting or an off-topic question is not mistaken for a product.
    """
    if not text:
        return None
    for pattern, key in _TRIGGERS:
        if pattern.search(text):
            # A dedicated flow may decline a product it cannot price or ask
            # about; it then falls through to the open-ended category.
            if any(veto.search(text) for veto in _EXCLUSIONS.get(key, ())):
                continue
            return key
    if allow_fallback and FALLBACK_KEY and looks_like_a_product(text):
        return FALLBACK_KEY
    return None


#: Messages that are conversation, not a product.
_NOT_A_PRODUCT = re.compile(
    r"^\s*(hi|hey|hello|yo|ok|okay|yes|no|thanks|thank you|sure|hmm|what|why|how|"
    r"who|when|where|help|test|testing)\b\W*$",
    re.I,
)


def looks_like_a_product(text: str) -> bool:
    """Cheap guard before treating free text as a product name."""
    from ..utils import normalise_product

    stripped = (text or "").strip()
    if len(stripped) < 2 or _NOT_A_PRODUCT.match(stripped):
        return False
    # After stripping quantities, units and filler there must be a noun left.
    return bool(normalise_product(stripped))


def quick_options() -> list[dict[str, str]]:
    """Opening chips shown by the chatbot."""
    return [
        {"label": f"{c.emoji} {c.label}", "value": c.label, "category": c.key}
        for c in CATEGORIES.values()
    ]


def slot_labels(category_key: str) -> dict[str, str]:
    category = get(category_key)
    if category is None:
        return {}
    return {s.name: s.display_label() for s in category.slots}


def describe(category_key: str, spec: dict[str, Any]) -> str:
    category = get(category_key)
    return category.spec_description(spec) if category else str(category_key)


__all__ = [
    "Category", "Slab", "Slot", "CATEGORIES", "FALLBACK_KEY", "get", "require",
    "all_categories", "detect", "looks_like_a_product", "quick_options",
    "slot_labels", "describe",
]
