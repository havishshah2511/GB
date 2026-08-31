"""Refrigerator category.

Same shape as the AC flow: the questions that actually change the price are
grouping fields, everything else stays on the intent. Capacity, door type and
defrost decide what a supplier is quoting for, so those three form the group.
"""
from __future__ import annotations

from .base import Category, Slab, Slot

FRIDGE_SLOTS = (
    Slot(
        name="capacity",
        label="Capacity",
        question="What size are you looking for?",
        priority=20,
        chips=("Up to 200 L", "200-300 L", "300-500 L", "500 L+", "Not Sure"),
        synonyms={
            "Up to 200 L": (
                r"\b(?:up\s*to\s*)?1\d{2}\s*(?:l|ltr|litre|liter)s?\b",
                r"\bunder\s*200\b", r"\bsmall\b", r"\bmini\b", r"\bsingle\s*door\s*size\b",
            ),
            "200-300 L": (
                r"\b2\d{2}\s*(?:l|ltr|litre|liter)s?\b", r"\b200\s*[-to]+\s*300\b",
                r"\bmedium\b",
            ),
            "300-500 L": (
                r"\b3\d{2}\s*(?:l|ltr|litre|liter)s?\b", r"\b4\d{2}\s*(?:l|ltr|litre|liter)s?\b",
                r"\b300\s*[-to]+\s*500\b", r"\blarge\b",
            ),
            "500 L+": (
                r"\b[5-9]\d{2}\s*(?:l|ltr|litre|liter)s?\b", r"\b\d{4}\s*(?:l|ltr|litre)s?\b",
                r"\b500\s*(?:l|ltr|litre)?\s*\+", r"\bextra\s*large\b",
            ),
            "Not Sure": (r"\bnot\s*sure\b", r"\bno\s*idea\b", r"\bdon'?t\s*know\b"),
        },
        grouping=True,
    ),
    Slot(
        name="door_type",
        label="Door type",
        question="Single door, double door or side-by-side?",
        priority=25,
        chips=("Single Door", "Double Door", "Side-by-Side", "Not Sure"),
        synonyms={
            "Single Door": (r"\bsingle\s*door\b", r"\b1\s*door\b", r"\bek\s*door\b"),
            "Double Door": (r"\bdouble\s*door\b", r"\b2\s*door\b", r"\bdo\s*door\b",
                            r"\btop\s*mount\b", r"\bbottom\s*mount\b"),
            "Side-by-Side": (r"\bside\s*[-by]*\s*side\b", r"\bsbs\b", r"\bfrench\s*door\b",
                             r"\bmulti\s*door\b", r"\btriple\s*door\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
    ),
    Slot(
        name="defrost",
        label="Cooling type",
        question="Direct Cool or Frost Free?",
        priority=30,
        chips=("Direct Cool", "Frost Free", "Not Sure"),
        synonyms={
            "Direct Cool": (r"\bdirect\s*cool\b", r"\bmanual\s*defrost\b", r"\bnormal\b"),
            "Frost Free": (r"\bfrost\s*free\b", r"\bfrostfree\b", r"\bno\s*frost\b",
                           r"\bauto\s*defrost\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
        # A single-door fridge is direct cool in practice; asking would be noise.
        ask_if=lambda s: str(s.get("door_type", "")).lower() != "single door",
    ),
    Slot(
        name="preferred_brand",
        label="Preferred brand",
        question="Any preferred brand?",
        priority=35,
        chips=("LG", "Samsung", "Whirlpool", "Godrej", "Haier", "No Preference"),
        synonyms={
            "LG": (r"\blg\b",),
            "Samsung": (r"\bsamsung\b", r"\bsamsang\b"),
            "Whirlpool": (r"\bwhirlpool\b", r"\bwhirpool\b"),
            "Godrej": (r"\bgodrej\b", r"\bgodrey\b"),
            "Haier": (r"\bhaier\b", r"\bhier\b"),
            "Bosch": (r"\bbosch\b",),
            "Panasonic": (r"\bpanasonic\b",),
            "Voltas Beko": (r"\bvoltas\s*beko\b", r"\bbeko\b"),
            "Hitachi": (r"\bhitachi\b",),
            "No Preference": (r"\bno\s*preference\b", r"\bany\s*brand\b", r"\bnot\s*fixed\b"),
        },
        freeform=True,
    ),
    Slot(
        name="brand_flexible",
        label="Brand flexibility",
        question=(
            "If another reliable brand gives you a significantly better group price, "
            "would you consider it?"
        ),
        priority=40,
        kind="bool",
        chips=("Yes", "{brand} Only"),
        synonyms={
            "yes": (r"\byes\b", r"\bsure\b", r"\bok(ay)?\b", r"\bwhy not\b", r"\bopen\b",
                    r"\bconsider\b", r"\bhaan\b"),
            "no": (r"\bno\b", r"\bonly\b", r"\bstrictly\b", r"\bmust be\b", r"\bnahi\b"),
        },
        ask_if=lambda s: str(s.get("preferred_brand", "")).lower() not in ("", "no preference"),
    ),
    Slot(
        name="star_rating",
        label="Star rating",
        question="Any star rating preference?",
        # Immediately after the brand questions, matching the AC flow.
        priority=42,
        chips=("3 Star", "5 Star", "No Preference"),
        synonyms={
            "2 Star": (r"\b2\s*star\b", r"\btwo\s*star\b"),
            "3 Star": (r"\b3\s*star\b", r"\bthree\s*star\b"),
            "4 Star": (r"\b4\s*star\b", r"\bfour\s*star\b"),
            "5 Star": (r"\b5\s*star\b", r"\bfive\s*star\b"),
            "No Preference": (r"\bno\s*preference\b", r"\bany\b", r"\bdoesn'?t matter\b"),
        },
        required=True,
    ),
    Slot(
        name="usage",
        label="Use",
        question="Is this for home, a shop, or a restaurant/hotel?",
        priority=50,
        chips=("Home", "Shop", "Restaurant / Hotel", "Office"),
        synonyms={
            "Home": (r"\bhome\b", r"\bhouse\b", r"\bpersonal\b", r"\bghar\b", r"\bfamily\b"),
            "Shop": (r"\bshop\b", r"\bstore\b", r"\bretail\b", r"\bdukan\b", r"\bkirana\b"),
            "Restaurant / Hotel": (r"\brestaurant\b", r"\bhotel\b", r"\bcafe\b", r"\bkitchen\b",
                                   r"\bcatering\b", r"\bdhaba\b"),
            "Office": (r"\boffice\b", r"\bpantry\b", r"\bstaff\b"),
        },
        required=False,
    ),
    Slot(
        name="old_exchange",
        label="Old unit exchange",
        question="Do you have an old fridge to exchange?",
        priority=58,
        kind="bool",
        chips=("Yes, exchange it", "No exchange"),
        synonyms={
            "yes": (r"\byes\b", r"\bexchange\b", r"\bpurana\b", r"\bold\s*one\b"),
            "no": (r"\bno\b", r"\bnew\s*only\b", r"\bnahi\b", r"\bnothing\b"),
        },
        required=False,
    ),
    Slot(
        name="budget",
        label="Budget per unit",
        question="Do you have a budget per fridge in mind? (optional)",
        priority=60,
        kind="number",
        chips=("Under ₹20,000", "₹20,000 - ₹40,000", "Above ₹40,000", "Skip"),
        required=False,
    ),
)

# Reference (slab 1) prices are the "regular price" shown struck-through.
FRIDGE_SLABS: dict[str, tuple[Slab, ...]] = {
    "FRIDGE|up_to_200_l|single_door|any": (
        Slab(1, 5, 18000), Slab(6, 10, 17300), Slab(11, 20, 16600),
        Slab(21, 30, 15900), Slab(31, 50, 15200), Slab(51, None, 14500),
    ),
    "FRIDGE|200-300_l|double_door|frost_free": (
        Slab(1, 5, 32000), Slab(6, 10, 30800), Slab(11, 20, 29600),
        Slab(21, 30, 28400), Slab(31, 50, 27200), Slab(51, None, 26000),
    ),
    "FRIDGE|200-300_l|double_door|direct_cool": (
        Slab(1, 5, 27000), Slab(6, 10, 26000), Slab(11, 20, 25000),
        Slab(21, 30, 24000), Slab(31, 50, 23000), Slab(51, None, 22000),
    ),
    "FRIDGE|300-500_l|double_door|frost_free": (
        Slab(1, 5, 46000), Slab(6, 10, 44300), Slab(11, 20, 42600),
        Slab(21, 30, 40900), Slab(31, 50, 39200), Slab(51, None, 37500),
    ),
    "FRIDGE|500_l+|side-by-side|frost_free": (
        Slab(1, 5, 78000), Slab(6, 10, 75000), Slab(11, 20, 72000),
        Slab(21, 30, 69000), Slab(31, 50, 66000), Slab(51, None, 63000),
    ),
}

CATEGORY = Category(
    key="FRIDGE",
    label="Refrigerator",
    plural_label="refrigerators",
    emoji="🧊",
    unit="fridge",
    unit_plural="fridges",
    product_noun="Refrigerator",
    quantity_question="How many refrigerators are you looking for?",
    quantity_chips=("1", "2", "3", "5+"),
    slots=FRIDGE_SLOTS,
    grouping_fields=("capacity", "door_type", "defrost"),
    slabs=FRIDGE_SLABS,
    default_slab_key="FRIDGE|200-300_l|double_door|frost_free",
    grouping_defaults={
        "capacity": "200-300 L", "door_type": "Double Door", "defrost": "Frost Free",
    },
    triggers=(
        r"\bfridge\b", r"\bfridges\b", r"\brefrigerator", r"\brefrigrator",
        r"\brefridgerator", r"\bfrig\b",
    ),
    # This flow asks household questions and prices off household slab tables.
    # Commercial cold storage is a different purchase, quoted differently, so it
    # goes to the open-ended category and waits for a real supplier quote.
    exclusions=(
        r"\bdeep\s*freezer\b", r"\bchest\s*freezer\b", r"\bwalk[\s-]*in\b",
        r"\bcold\s*room\b", r"\bcommercial\b", r"\bindustrial\b", r"\bdisplay\b",
        r"\bbottle\s*cooler\b", r"\bblast\b", r"\bbakery\b", r"\bdairy\b",
        r"\bpharmacy\b", r"\blaborator", r"\bunder[\s-]*counter\b", r"\bvisi\s*cooler\b",
    ),
    # A number is a quantity only when it is NOT immediately followed by a spec
    # unit (litres / star / door): "2 LG 300 L double door fridge" -> 2.
    quantity_patterns=(
        (
            r"\b(\d{1,4})(?!\s*\.\d)(?!\s*(?:l\b|ltr|litre|liter|star|door|%))"
            r"(?:\s+[\w\.\-]+){0,5}?\s*"
            r"(?:fridges?\b|refrig\w*|refridg\w*)",
            1.0,
        ),
    ),
    brand_field="preferred_brand",
    intro="Refrigerators price by volume — dealers discount hard once quantity adds up.",
)
