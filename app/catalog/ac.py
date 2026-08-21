"""Air Conditioner category."""
from __future__ import annotations

from .base import Category, Slab, Slot

AC_SLOTS = (
    Slot(
        name="capacity",
        label="Capacity",
        question="Do you know what capacity you need?",
        priority=20,
        chips=("1 Ton", "1.5 Ton", "2 Ton", "Not Sure"),
        synonyms={
            "1 Ton": (r"\b1\s*(ton|tr)\b", r"\bone\s*ton\b"),
            "1.5 Ton": (r"\b1[\.,]5\s*(ton|tr)?\b", r"\bone\s*and\s*half\s*ton\b", r"\b1\.5\b"),
            "2 Ton": (r"\b2\s*(ton|tr)\b", r"\btwo\s*ton\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bno\s*idea\b", r"\bdon'?t\s*know\b"),
        },
        grouping=True,
    ),
    Slot(
        name="ac_type",
        label="Type",
        question="Split or Window?",
        priority=25,
        chips=("Split", "Window", "Not Sure"),
        synonyms={
            "Split": (r"\bsplit\b",),
            "Window": (r"\bwindow\b", r"\bwindo\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
    ),
    Slot(
        name="inverter",
        label="Inverter",
        question="Inverter or Non-Inverter?",
        priority=30,
        chips=("Inverter", "Non-Inverter", "Not Sure"),
        synonyms={
            "Inverter": (r"\binverter\b", r"\binvertor\b"),
            "Non-Inverter": (r"\bnon[\s\-]?inverter\b", r"\bnon[\s\-]?invertor\b", r"\bfixed\s*speed\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
        ask_if=lambda s: str(s.get("ac_type", "")).lower() != "window",
    ),
    Slot(
        name="preferred_brand",
        label="Preferred brand",
        question="Any preferred brand?",
        priority=35,
        chips=("Daikin", "Voltas", "LG", "Blue Star", "Hitachi", "No Preference"),
        synonyms={
            "Daikin": (r"\bdaikin\b", r"\bdiakin\b", r"\bdaiken\b"),
            "Voltas": (r"\bvoltas\b", r"\bvoltage?s\b"),
            "LG": (r"\blg\b",),
            "Blue Star": (r"\bblue\s*star\b", r"\bbluestar\b"),
            "Hitachi": (r"\bhitachi\b", r"\bhitachii\b"),
            "Samsung": (r"\bsamsung\b",),
            "Carrier": (r"\bcarrier\b",),
            "Panasonic": (r"\bpanasonic\b",),
            "Godrej": (r"\bgodrej\b",),
            "Whirlpool": (r"\bwhirlpool\b",),
            "O General": (r"\bo\s*general\b", r"\bogeneral\b"),
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
            "yes": (r"\byes\b", r"\bsure\b", r"\bok(ay)?\b", r"\bwhy not\b", r"\bopen\b", r"\bconsider\b"),
            "no": (r"\bno\b", r"\bonly\b", r"\bstrictly\b", r"\bmust be\b"),
        },
        ask_if=lambda s: str(s.get("preferred_brand", "")).lower() not in ("", "no preference"),
    ),
    Slot(
        name="star_rating",
        label="Star rating",
        question="Any star rating preference?",
        # Straight after the brand questions: rating and brand are the two
        # things a buyer weighs together, and asking them side by side reads
        # better than returning to it once location and dates are done.
        priority=42,
        chips=("3 Star", "5 Star", "No Preference"),
        synonyms={
            "3 Star": (r"\b3\s*star\b", r"\bthree\s*star\b"),
            "4 Star": (r"\b4\s*star\b", r"\bfour\s*star\b"),
            "5 Star": (r"\b5\s*star\b", r"\bfive\s*star\b"),
            "No Preference": (r"\bno\s*preference\b", r"\bany\b", r"\bdoesn'?t matter\b"),
        },
        # Always asked, so it holds its place in the sequence. Optional slots
        # are capped at two per conversation and can be dropped entirely, which
        # made it appear only sometimes. "No Preference" is one tap.
        required=True,
    ),
    Slot(
        name="installation_required",
        label="Installation",
        question="Will you need installation included?",
        priority=58,
        kind="bool",
        chips=("Yes, include installation", "No, I'll arrange it"),
        synonyms={
            "yes": (r"\byes\b", r"\binclude\b", r"\bneed(ed)?\b", r"\bwith install", r"\brequired\b"),
            "no": (r"\bno\b", r"\barrange\b", r"\bmyself\b", r"\bnot required\b"),
        },
        required=False,
    ),
    Slot(
        name="budget",
        label="Budget per unit",
        question="Do you have a budget per AC in mind? (optional)",
        priority=60,
        kind="number",
        chips=("Under ₹35,000", "₹35,000 - ₹45,000", "Above ₹45,000", "Skip"),
        required=False,
    ),
)

# Reference (slab 1) prices are the "regular price" shown struck-through.
AC_SLABS: dict[str, tuple[Slab, ...]] = {
    "AC|1_ton|split|inverter": (
        Slab(1, 5, 34000), Slab(6, 10, 32800), Slab(11, 20, 31500),
        Slab(21, 30, 30200), Slab(31, 50, 28900), Slab(51, None, 27600),
    ),
    "AC|1.5_ton|split|inverter": (
        Slab(1, 5, 40000), Slab(6, 10, 38500), Slab(11, 20, 37000),
        Slab(21, 30, 35500), Slab(31, 50, 34000), Slab(51, None, 32500),
    ),
    "AC|2_ton|split|inverter": (
        Slab(1, 5, 48000), Slab(6, 10, 46200), Slab(11, 20, 44400),
        Slab(21, 30, 42600), Slab(31, 50, 40800), Slab(51, None, 39000),
    ),
    "AC|1_ton|window|any": (
        Slab(1, 5, 28000), Slab(6, 10, 27000), Slab(11, 20, 25900),
        Slab(21, 30, 24800), Slab(31, 50, 23800), Slab(51, None, 22800),
    ),
    "AC|1.5_ton|window|any": (
        Slab(1, 5, 33000), Slab(6, 10, 31800), Slab(11, 20, 30500),
        Slab(21, 30, 29300), Slab(31, 50, 28000), Slab(51, None, 26800),
    ),
}

CATEGORY = Category(
    key="AC",
    label="Air Conditioner",
    emoji="❄️",
    unit="AC",
    unit_plural="ACs",
    quantity_question="How many ACs are you looking for?",
    quantity_chips=("1", "2", "3", "5+"),
    slots=AC_SLOTS,
    grouping_fields=("capacity", "ac_type", "inverter"),
    slabs=AC_SLABS,
    default_slab_key="AC|1.5_ton|split|inverter",
    grouping_defaults={"capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter"},
    triggers=(
        r"\ba[./]?\s?c\.?\b", r"\bacs\b", r"\bair\s*condition", r"\baircon\b",
        r"\bsplit\s*ac\b", r"\bwindow\s*ac\b", r"\bcooling\b",
    ),
    # This flow asks split-or-window and prices off the split-AC slab tables.
    # Every other kind of air conditioning is a different purchase, quoted
    # differently, so it goes to the open-ended category instead of being
    # forced through questions that do not apply and priced off the wrong
    # table. Add slabs and options here when one is worth its own flow.
    exclusions=(
        r"\bcassette\b", r"\bductable\b", r"\bducted\b", r"\bvrf\b", r"\bvrv\b",
        r"\bpackage[d]?\s*ac\b", r"\btower\s*ac\b", r"\bfloor[\s-]*stand",
        r"\bprecision\b", r"\bindustrial\b", r"\bportable\b", r"\bchiller\b",
        r"\bahu\b", r"\bfcu\b", r"\bcold\s*room\b",
    ),
    # A number is a quantity only when it is NOT immediately followed by a spec
    # unit (ton / star), and it may sit a few words ahead of the product noun:
    # "2 Daikin 1.5 ton split inverter AC" -> 2.
    quantity_patterns=(
        (
            r"\b(\d{1,4})(?!\s*\.\d)(?!\s*(?:ton|tonne|tr|star|kg|%))"
            r"(?:\s+[\w\.\-]+){0,5}?\s*"
            r"(?:a\.?\s?c\.?s?\b|air\s*condition\w*)",
            1.0,
        ),
    ),
    brand_field="preferred_brand",
    intro="Air conditioners are one of the best categories for group buying — dealers price them by volume.",
)
