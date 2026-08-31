"""Television category.

Same shape as the AC and refrigerator flows. Screen size, panel technology and
resolution are what a supplier quotes against, so those three form the group;
everything else (smart, brand, wall mount, use) stays on the intent.
"""
from __future__ import annotations

from .base import Category, Slab, Slot

TV_SLOTS = (
    Slot(
        name="screen_size",
        label="Screen size",
        question="What screen size are you looking for?",
        priority=20,
        chips=('32 inch', '43 inch', '50-55 inch', '65 inch+', "Not Sure"),
        synonyms={
            "32 inch": (r"\b32\s*(?:inch|inches|\"|'')?\b", r"\bthirty\s*two\b"),
            "43 inch": (r"\b4[0-3]\s*(?:inch|inches|\"|'')?\b", r"\bforty\s*three\b"),
            "50-55 inch": (
                r"\b(?:4[5-9]|5[0-9])\s*(?:inch|inches|\"|'')?\b",
                r"\b50\s*[-to]+\s*55\b", r"\bfifty\b", r"\bfifty\s*five\b",
            ),
            "65 inch+": (
                r"\b(?:6[0-9]|7[0-9]|8[0-9]|9[0-9])\s*(?:inch|inches|\"|'')?\b",
                r"\bsixty\s*five\b", r"\b65\s*\+",
            ),
            "Not Sure": (r"\bnot\s*sure\b", r"\bno\s*idea\b", r"\bdon'?t\s*know\b"),
        },
        grouping=True,
    ),
    Slot(
        name="display_type",
        label="Panel",
        question="LED, QLED or OLED?",
        priority=25,
        chips=("LED", "QLED", "OLED", "Not Sure"),
        synonyms={
            # QLED/OLED first: a bare "led" must not swallow them.
            "QLED": (r"\bq[\s\-]?led\b", r"\bqled\b", r"\bneo\s*qled\b"),
            "OLED": (r"\bo[\s\-]?led\b", r"\boled\b"),
            "LED": (r"\bled\b", r"\blcd\b", r"\bnormal\b", r"\bregular\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
    ),
    Slot(
        name="resolution",
        label="Resolution",
        question="What resolution?",
        priority=30,
        chips=("HD Ready", "Full HD", "4K UHD", "8K", "Not Sure"),
        synonyms={
            "8K": (r"\b8\s*k\b",),
            "4K UHD": (r"\b4\s*k\b", r"\buhd\b", r"\bultra\s*hd\b", r"\b2160p?\b"),
            "Full HD": (r"\bfull\s*hd\b", r"\bfhd\b", r"\b1080p?\b"),
            "HD Ready": (r"\bhd\s*ready\b", r"\bhd\b", r"\b720p?\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
    ),
    Slot(
        name="smart_tv",
        label="Smart TV",
        question="Smart TV or basic?",
        priority=32,
        chips=("Smart TV", "Basic (non-smart)", "Not Sure"),
        synonyms={
            "Smart TV": (r"\bsmart\b", r"\bandroid\b", r"\bgoogle\s*tv\b", r"\bwebos\b",
                         r"\btizen\b", r"\bnetflix\b", r"\byoutube\b", r"\bwifi\b"),
            "Basic (non-smart)": (r"\bnon[\s\-]?smart\b", r"\bbasic\b", r"\bsimple\b",
                                  r"\bnormal\s*tv\b", r"\bno\s*internet\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        required=False,
    ),
    Slot(
        name="preferred_brand",
        label="Preferred brand",
        question="Any preferred brand?",
        priority=35,
        chips=("Samsung", "LG", "Sony", "TCL", "Xiaomi", "No Preference"),
        synonyms={
            "Samsung": (r"\bsamsung\b", r"\bsamsang\b"),
            "LG": (r"\blg\b",),
            "Sony": (r"\bsony\b", r"\bbravia\b"),
            "TCL": (r"\btcl\b",),
            "Xiaomi": (r"\bxiaomi\b", r"\bmi\s*tv\b", r"\bredmi\b"),
            "OnePlus": (r"\bone\s*plus\b", r"\boneplus\b"),
            "Hisense": (r"\bhisense\b",),
            "Panasonic": (r"\bpanasonic\b",),
            "Vu": (r"\bvu\b",),
            "Haier": (r"\bhaier\b",),
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
        name="usage",
        label="Use",
        question="Where will these be used?",
        # Sits where star rating does on the other flows: straight after brand.
        priority=42,
        chips=("Home", "Hotel rooms", "Office", "Showroom / Shop", "Restaurant"),
        synonyms={
            "Home": (r"\bhome\b", r"\bhouse\b", r"\bpersonal\b", r"\bghar\b", r"\bfamily\b"),
            "Hotel rooms": (r"\bhotel\b", r"\bresort\b", r"\bguest\s*house\b", r"\brooms?\b",
                            r"\bhostel\b"),
            "Office": (r"\boffice\b", r"\bconference\b", r"\bmeeting\b", r"\breception\b"),
            "Showroom / Shop": (r"\bshowroom\b", r"\bshop\b", r"\bstore\b", r"\bretail\b"),
            "Restaurant": (r"\brestaurant\b", r"\bcafe\b", r"\bbar\b", r"\bdhaba\b"),
        },
        required=False,
    ),
    Slot(
        name="wall_mount",
        label="Wall mount",
        question="Do you need wall mounting included?",
        priority=58,
        kind="bool",
        chips=("Yes, include mounting", "No, table stand is fine"),
        synonyms={
            "yes": (r"\byes\b", r"\bwall\b", r"\bmount\b", r"\binclude\b", r"\bbracket\b"),
            "no": (r"\bno\b", r"\btable\b", r"\bstand\b", r"\bmyself\b", r"\bnot required\b"),
        },
        required=False,
    ),
    Slot(
        name="budget",
        label="Budget per unit",
        question="Do you have a budget per TV in mind? (optional)",
        priority=60,
        kind="number",
        chips=("Under ₹20,000", "₹20,000 - ₹50,000", "Above ₹50,000", "Skip"),
        required=False,
    ),
)

# Reference (slab 1) prices are the "regular price" shown struck-through.
TV_SLABS: dict[str, tuple[Slab, ...]] = {
    "TV|32_inch|led|hd_ready": (
        Slab(1, 5, 14000), Slab(6, 10, 13500), Slab(11, 20, 13000),
        Slab(21, 30, 12500), Slab(31, 50, 12000), Slab(51, None, 11500),
    ),
    "TV|43_inch|led|full_hd": (
        Slab(1, 5, 24000), Slab(6, 10, 23100), Slab(11, 20, 22200),
        Slab(21, 30, 21300), Slab(31, 50, 20400), Slab(51, None, 19500),
    ),
    "TV|43_inch|led|4k_uhd": (
        Slab(1, 5, 28000), Slab(6, 10, 26900), Slab(11, 20, 25900),
        Slab(21, 30, 24900), Slab(31, 50, 23900), Slab(51, None, 22900),
    ),
    "TV|50-55_inch|led|4k_uhd": (
        Slab(1, 5, 42000), Slab(6, 10, 40400), Slab(11, 20, 38800),
        Slab(21, 30, 37200), Slab(31, 50, 35600), Slab(51, None, 34000),
    ),
    "TV|50-55_inch|qled|4k_uhd": (
        Slab(1, 5, 62000), Slab(6, 10, 59600), Slab(11, 20, 57200),
        Slab(21, 30, 54800), Slab(31, 50, 52400), Slab(51, None, 50000),
    ),
    "TV|50-55_inch|oled|4k_uhd": (
        Slab(1, 5, 125000), Slab(6, 10, 120000), Slab(11, 20, 115000),
        Slab(21, 30, 110000), Slab(31, 50, 105000), Slab(51, None, 100000),
    ),
    "TV|65_inch+|led|4k_uhd": (
        Slab(1, 5, 72000), Slab(6, 10, 69200), Slab(11, 20, 66400),
        Slab(21, 30, 63600), Slab(31, 50, 60800), Slab(51, None, 58000),
    ),
    "TV|65_inch+|qled|4k_uhd": (
        Slab(1, 5, 105000), Slab(6, 10, 101000), Slab(11, 20, 97000),
        Slab(21, 30, 93000), Slab(31, 50, 89000), Slab(51, None, 85000),
    ),
}

CATEGORY = Category(
    key="TV",
    label="Television",
    plural_label="televisions",
    emoji="📺",
    unit="TV",
    unit_plural="TVs",
    quantity_question="How many TVs are you looking for?",
    quantity_chips=("1", "2", "5", "10+"),
    slots=TV_SLOTS,
    grouping_fields=("screen_size", "display_type", "resolution"),
    slabs=TV_SLABS,
    default_slab_key="TV|43_inch|led|4k_uhd",
    grouping_defaults={
        "screen_size": "43 inch", "display_type": "LED", "resolution": "4K UHD",
    },
    triggers=(
        r"\btvs?\b", r"\btelevision", r"\bled\s*tv\b", r"\bsmart\s*tv\b",
        r"\bqled\b", r"\boled\b", r"\btelly\b",
    ),
    # Commercial display hardware is a different purchase, quoted differently,
    # so it goes to the open-ended category and waits for a real quote.
    exclusions=(
        r"\bcommercial\s*display\b", r"\bdigital\s*signage\b", r"\bsignage\b",
        r"\bvideo\s*wall\b", r"\binteractive\s*panel\b", r"\bprojector\b",
        r"\bmonitor\b", r"\bkiosk\b", r"\bled\s*wall\b", r"\bindustrial\b",
    ),
    # A number is a quantity only when it is NOT immediately followed by a spec
    # unit (inch / k / p): "5 Samsung 43 inch 4K TV" -> 5.
    quantity_patterns=(
        (
            r"\b(\d{1,4})(?!\s*\.\d)(?!\s*(?:inch|inches|\"|''|k\b|p\b|hd\b|%))"
            r"(?:\s+[\w\.\-\"]+){0,5}?\s*"
            r"(?:tvs?\b|television\w*)",
            1.0,
        ),
    ),
    brand_field="preferred_brand",
    intro="TVs discount steeply by volume — hotels and offices buying together do well here.",
)
