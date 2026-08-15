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

_MODULES = ("ac", "rice")

CATEGORIES: dict[str, Category] = {}
for _name in _MODULES:
    _cat = importlib.import_module(f"{__name__}.{_name}").CATEGORY
    CATEGORIES[_cat.key] = _cat

_TRIGGERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.I), cat.key)
    for cat in CATEGORIES.values()
    for pattern in cat.triggers
]


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


def detect(text: str) -> str | None:
    """Route free text to a category key."""
    if not text:
        return None
    for pattern, key in _TRIGGERS:
        if pattern.search(text):
            return key
    return None


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
    "Category", "Slab", "Slot", "CATEGORIES", "get", "require", "all_categories",
    "detect", "quick_options", "slot_labels", "describe",
]
