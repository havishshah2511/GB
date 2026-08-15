"""Rice category. Quantity is tracked in kilograms."""
from __future__ import annotations

from .base import Category, Slab, Slot

RICE_SLOTS = (
    Slot(
        name="rice_type",
        label="Rice type",
        question="Which type of rice do you need?",
        priority=20,
        chips=("Basmati", "Sona Masoori", "Ponni", "Kolam", "Other / Not Sure"),
        synonyms={
            "Basmati": (r"\bbasmati\b", r"\bbasmathi\b", r"\bbasmati\s*rice\b", r"\bbasmatti\b"),
            "Sona Masoori": (r"\bsona\s*masoori\b", r"\bsona\s*masuri\b", r"\bsonamasoori\b"),
            "Ponni": (r"\bponni\b",),
            "Kolam": (r"\bkolam\b", r"\bkolum\b"),
            "Idli Rice": (r"\bidli\s*rice\b", r"\bidly\s*rice\b"),
            "Other / Not Sure": (r"\bnot\s*sure\b", r"\bany\b", r"\bother\b", r"\bnormal\s*rice\b"),
        },
        grouping=True,
        freeform=True,
    ),
    Slot(
        name="grade",
        label="Quality",
        question="What quality grade are you looking for?",
        priority=30,
        chips=("Premium", "Standard", "Economy"),
        synonyms={
            "Premium": (r"\bpremium\b", r"\bbest\b", r"\btop\s*quality\b", r"\bsuperior\b", r"\ba\s*grade\b"),
            "Standard": (r"\bstandard\b", r"\bregular\b", r"\bnormal\b", r"\bmedium\b"),
            "Economy": (r"\beconomy\b", r"\bcheap(est)?\b", r"\bbudget\b", r"\bbulk\s*grade\b"),
        },
        grouping=True,
    ),
    Slot(
        name="usage",
        label="Use case",
        question="Is this for personal use, a restaurant, catering or business?",
        priority=35,
        chips=("Personal", "Restaurant", "Catering", "Business / Reseller"),
        synonyms={
            "Personal": (r"\bpersonal\b", r"\bhome\b", r"\bfamily\b", r"\bhousehold\b"),
            "Restaurant": (r"\brestaurant\b", r"\bhotel\b", r"\bdhaba\b", r"\bcafe\b", r"\bkitchen\b"),
            "Catering": (r"\bcater(ing|er)?\b", r"\bevents?\b", r"\bbanquet\b", r"\bmess\b"),
            "Business / Reseller": (r"\bbusiness\b", r"\bresell(er)?\b", r"\bshop\b", r"\bretail\b", r"\btrade\b"),
        },
    ),
    Slot(
        name="brand_preference",
        label="Preferred brand",
        question="Any preferred brand?",
        priority=40,
        chips=("India Gate", "Daawat", "Kohinoor", "Local Mill", "No Preference"),
        synonyms={
            "India Gate": (r"\bindia\s*gate\b",),
            "Daawat": (r"\bdaawat\b", r"\bdawat\b"),
            "Kohinoor": (r"\bkohinoor\b", r"\bkohinur\b"),
            "Fortune": (r"\bfortune\b",),
            "Local Mill": (r"\blocal\s*(mill|brand)\b", r"\bloose\b", r"\bopen\s*rice\b"),
            "No Preference": (r"\bno\s*preference\b", r"\bany\s*brand\b", r"\bwhatever\b"),
        },
        freeform=True,
    ),
    Slot(
        name="brand_flexible",
        label="Brand flexibility",
        question=(
            "If another good-quality brand gives a significantly better group price, "
            "would you consider it?"
        ),
        priority=45,
        kind="bool",
        chips=("Yes", "{brand} Only"),
        synonyms={
            "yes": (r"\byes\b", r"\bsure\b", r"\bok(ay)?\b", r"\bopen\b", r"\bconsider\b"),
            "no": (r"\bno\b", r"\bonly\b", r"\bstrictly\b", r"\bmust be\b"),
        },
        ask_if=lambda s: str(s.get("brand_preference", "")).lower() not in ("", "no preference"),
    ),
    Slot(
        name="package_size",
        label="Pack size",
        question="What pack size works for you?",
        priority=55,
        chips=("5 kg", "10 kg", "25 kg", "26 kg", "No Preference"),
        synonyms={
            "5 kg": (r"\b5\s*kgs?\s*(bag|pack)\b",),
            "10 kg": (r"\b10\s*kgs?\s*(bag|pack)\b",),
            "25 kg": (r"\b25\s*kgs?\s*(bag|pack)\b",),
            "26 kg": (r"\b26\s*kgs?\s*(bag|pack)\b",),
            "No Preference": (r"\bno\s*preference\b", r"\bany\b"),
        },
        required=False,
    ),
    Slot(
        name="recurring_monthly",
        label="Monthly requirement",
        question="Is this a repeat monthly requirement?",
        priority=58,
        kind="bool",
        chips=("Yes, every month", "No, one time"),
        synonyms={
            "yes": (r"\byes\b", r"\bevery\s*month\b", r"\bmonthly\b", r"\brepeat\b", r"\bregular\b"),
            "no": (r"\bno\b", r"\bone\s*time\b", r"\bonce\b"),
        },
        required=False,
        ask_if=lambda s: str(s.get("usage", "")).lower() != "personal",
    ),
    Slot(
        name="budget",
        label="Budget per kg",
        question="Any target price per kg? (optional)",
        priority=60,
        kind="number",
        chips=("Under ₹60", "₹60 - ₹90", "Above ₹90", "Skip"),
        required=False,
    ),
)

# Prices are per kilogram.
RICE_SLABS: dict[str, tuple[Slab, ...]] = {
    "RICE|basmati|premium": (
        Slab(1, 99, 95), Slab(100, 249, 90), Slab(250, 499, 86),
        Slab(500, 999, 82), Slab(1000, 2499, 78), Slab(2500, None, 74),
    ),
    "RICE|basmati|standard": (
        Slab(1, 99, 78), Slab(100, 249, 74), Slab(250, 499, 71),
        Slab(500, 999, 68), Slab(1000, 2499, 65), Slab(2500, None, 62),
    ),
    "RICE|basmati|economy": (
        Slab(1, 99, 64), Slab(100, 249, 61), Slab(250, 499, 58),
        Slab(500, 999, 56), Slab(1000, 2499, 53), Slab(2500, None, 51),
    ),
    "RICE|sona_masoori|premium": (
        Slab(1, 99, 62), Slab(100, 249, 59), Slab(250, 499, 56),
        Slab(500, 999, 54), Slab(1000, 2499, 51), Slab(2500, None, 49),
    ),
    "RICE|sona_masoori|standard": (
        Slab(1, 99, 54), Slab(100, 249, 51), Slab(250, 499, 49),
        Slab(500, 999, 47), Slab(1000, 2499, 45), Slab(2500, None, 43),
    ),
    "RICE|ponni|standard": (
        Slab(1, 99, 58), Slab(100, 249, 55), Slab(250, 499, 53),
        Slab(500, 999, 51), Slab(1000, 2499, 48), Slab(2500, None, 46),
    ),
    "RICE|kolam|standard": (
        Slab(1, 99, 56), Slab(100, 249, 53), Slab(250, 499, 51),
        Slab(500, 999, 49), Slab(1000, 2499, 47), Slab(2500, None, 45),
    ),
}

CATEGORY = Category(
    key="RICE",
    label="Rice",
    emoji="🍚",
    unit="kg",
    unit_plural="kg",
    quantity_question="How many kilograms do you need?",
    quantity_chips=("25 kg", "50 kg", "100 kg", "500 kg"),
    slots=RICE_SLOTS,
    grouping_fields=("rice_type", "grade"),
    slabs=RICE_SLABS,
    default_slab_key="RICE|basmati|standard",
    grouping_defaults={"rice_type": "Basmati", "grade": "Standard"},
    triggers=(r"\brice\b", r"\bbasmati\b", r"\bsona\s*masoori\b", r"\bponni\b", r"\bchawal\b", r"\bkolam\b"),
    quantity_patterns=(
        (r"(\d+(?:\.\d+)?)\s*(?:quintals?|qtl)\b", 100.0),
        (r"(\d+(?:\.\d+)?)\s*(?:tons?|tonnes?)\b", 1000.0),
        (r"(\d+(?:\.\d+)?)\s*(?:kgs?|kilo(?:gram)?s?)\b", 1.0),
        (r"(\d+(?:\.\d+)?)\s*(?:bags?)\b", 25.0),
    ),
    min_group_quantity=25,
    brand_field="brand_preference",
    product_noun="Rice",
    intro="Rice buys well in volume — mills quote much better rates once the combined tonnage grows.",
)
