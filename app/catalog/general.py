"""Any product.

AC and rice have negotiated slab tables. This category is for everything else:
the customer names the product, it is normalised into a grouping key, and
buyers wanting the same thing in the same city pool together.

Such a group starts with **no price**. That is deliberate and it is the honest
position -- nobody has quoted for it yet. The group collects quantity, the
operator takes the pooled demand to a supplier, enters the slabs they come back
with, and every member is told the moment a real price exists. The bot never
invents a number for a product we have not priced.
"""
from __future__ import annotations

from .base import Category, Slot

SLOTS = (
    Slot(
        name="product_name",
        question="What product are you looking to buy?",
        priority=5,
        kind="text",
        grouping=True,
        required=True,
        freeform=True,
        max_words=6,
        max_chars=60,
        label="Product",
        help_text="Anything — cement, LED bulbs, office chairs, packaging boxes…",
    ),
    Slot(
        name="variant",
        question=(
            "Any specific type, size or grade?\n\n"
            "This helps me pool you with buyers who want the same thing."
        ),
        priority=20,
        kind="text",
        chips=("No preference",),
        grouping=True,
        required=False,
        freeform=True,
        max_words=6,
        max_chars=60,
        label="Type / size / grade",
    ),
    Slot(
        name="brand_preference",
        question="Any preferred brand?",
        priority=30,
        kind="text",
        chips=("No Preference",),
        required=False,
        freeform=True,
        label="Preferred brand",
    ),
    Slot(
        name="brand_flexible",
        question=(
            "If another brand gives the group a significantly better price, "
            "would you consider it?"
        ),
        priority=32,
        kind="bool",
        chips=("Yes, if it saves money", "{brand} only"),
        required=True,
        label="Brand flexible",
        # Only worth asking once they have actually named a brand.
        ask_if=lambda state: bool(
            state.get("brand_preference")
            and str(state["brand_preference"]).strip().lower()
            not in ("no preference", "none", "any", "not sure")
        ),
    ),
)

CATEGORY = Category(
    key="GENERAL",
    label="Something else",
    emoji="🛒",
    unit="unit",
    unit_plural="units",
    quantity_question="How many do you need?",
    quantity_chips=("1", "5", "10", "25", "50", "100"),
    slots=SLOTS,
    grouping_fields=("product_name", "variant"),
    # No slab templates: an unpriced group is the correct starting state.
    slabs={},
    default_slab_key="",
    open_ended=True,
    brand_field="brand_preference",
    # No triggers -- this is the fallback when nothing else matches, chosen in
    # catalog.detect() rather than by pattern.
    triggers=(),
    min_group_quantity=1,
    intro="Tell me what you need and I'll find other buyers who want the same thing.",
)
