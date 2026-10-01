"""Plywood.

Counted in sheets, which is how it is quoted, stocked and delivered. Grade,
thickness and sheet size decide the price, so those three form the group;
core, finish, brand and application stay on the intent for the supplier.

Quantity is asked *after* the specification and before location: a plywood
buyer works out what board they need first, and "how many sheets?" only means
something once thickness and size are settled.
"""
from __future__ import annotations

from .base import Addon, Category, Slab, Slot

# What actually leaves the shop with a plywood order. Offering these turns one
# line item into a basket the operator can negotiate as a bundle, and captures
# demand we would otherwise never hear about.
#
# Each one points at a category of its own: picking it opens a couple of
# questions ("what size nails?") and the answers form a real buying group that
# pools with every other buyer wanting the same thing in the same city.
PLYWOOD_ADDONS = (
    Addon(
        key="adhesive", label="Adhesive", emoji="🧴",
        # Named by the brand every carpenter in India says out loud. The flow
        # still asks which brand they want and quotes whatever the group buys.
        hint="Fevicol, white glue, synthetic resin",
        category_key="ADHESIVE",
        synonyms=(r"\bfevicol\b", r"\bfevi\b", r"\badhesive\b", r"\bglue\b",
                  r"\bgond\b", r"\bsr\s*998\b", r"\bmarine\s*glue\b"),
    ),
    Addon(
        key="nails", label="Nails & pins", emoji="📌",
        hint="Wire nails, panel pins, brad nails",
        category_key="NAILS",
        synonyms=(r"\bnails?\b", r"\bpins?\b", r"\bkeel\b", r"\bbrad\b",
                  r"\bstaples?\b"),
    ),
    Addon(
        key="screws", label="Screws", emoji="🔩",
        hint="Wood screws, self-tapping screws",
        category_key="SCREWS",
        synonyms=(r"\bscrews?\b", r"\bpech\b", r"\bfasteners?\b"),
    ),
    Addon(
        key="hardware", label="Hinges & fittings", emoji="🚪",
        hint="Hinges, channels, handles, locks",
        category_key="FITTINGS",
        synonyms=(r"\bhinges?\b", r"\bfittings?\b", r"\bchannels?\b",
                  r"\bhandles?\b", r"\blocks?\b", r"\bhardware\b", r"\bkabza\b"),
    ),
    Addon(
        key="laminate", label="Laminate / sunmica", emoji="🎨",
        hint="Decorative laminate sheets",
        category_key="LAMINATE",
        synonyms=(r"\blaminate\b", r"\bsunmica\b", r"\bmica\b", r"\bdeco\b"),
    ),
    Addon(
        key="edge_band", label="Edge banding tape", emoji="🎗️",
        hint="PVC edge banding / beading",
        category_key="EDGEBAND",
        synonyms=(r"\bedge\s*band", r"\bbeading\b", r"\bpvc\s*tape\b", r"\bpatti\b"),
    ),
)

# Volume ladder, applied to a per-sheet base price. Expressing it as one curve
# keeps a dozen configurations auditable instead of ninety hand-typed numbers.
_BANDS: tuple[tuple[int, int | None], ...] = (
    (1, 25), (26, 50), (51, 100), (101, 250), (251, 500), (501, None),
)
_DISCOUNTS = (1.00, 0.96, 0.92, 0.88, 0.85, 0.82)


def ladder(base_price: float) -> tuple[Slab, ...]:
    """Six slabs from a 1-25 sheet reference price."""
    return tuple(
        Slab(low, high, round(base_price * factor / 10) * 10)
        for (low, high), factor in zip(_BANDS, _DISCOUNTS)
    )


PLYWOOD_SLOTS = (
    Slot(
        name="grade",
        label="Grade",
        # Not asked: the grade names are trade jargon and most buyers stall on
        # them. It is still read when volunteered ("marine ply", "IS 710",
        # "waterproof"), and otherwise takes the category default below, so
        # the group always has a grade a supplier can quote against.
        #
        # Note this is the biggest single price lever in the category -- an
        # 18 mm sheet is ~1,650 in MR and ~2,650 in BWP Marine -- so an
        # unvolunteered grade is quoted at the default, not averaged.
        asked=False,
        question=(
            "Which grade of plywood?\n\n"
            "MR is for dry interiors, BWR resists moisture, "
            "BWP/Marine survives water."
        ),
        priority=20,
        chips=("MR", "BWR", "BWP Marine", "Fire Retardant", "Not Sure"),
        synonyms={
            "BWP Marine": (r"\bbwp\b", r"\bmarine\b", r"\bis\s*:?\s*710\b", r"\b710\b",
                           r"\bwaterproof\b", r"\bwater\s*proof\b"),
            "BWR": (r"\bbwr\b", r"\bboiling\s*water\b", r"\bmoisture\s*resist",
                    r"\bsemi\s*waterproof\b"),
            "Fire Retardant": (r"\bfire\s*retardant\b", r"\bfr\s*grade\b", r"\bfrp?\b",
                               r"\bis\s*:?\s*5509\b"),
            "MR": (r"\bmr\b", r"\bmoisture\s*resistant\b", r"\bcommercial\b",
                   r"\binterior\b", r"\bis\s*:?\s*303\b", r"\b303\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bno\s*idea\b", r"\bdon'?t\s*know\b",
                         r"\bsuggest\b", r"\brecommend\b"),
        },
        grouping=True,
    ),
    Slot(
        name="thickness",
        label="Thickness",
        question="What thickness?",
        priority=24,
        chips=("6 mm", "9 mm", "12 mm", "16 mm", "18 mm", "25 mm", "Not Sure"),
        synonyms={
            "4 mm": (r"\b4\s*mm\b",),
            "6 mm": (r"\b6\s*mm\b",),
            "9 mm": (r"\b9\s*mm\b",),
            "12 mm": (r"\b12\s*mm\b",),
            "16 mm": (r"\b16\s*mm\b",),
            "18 mm": (r"\b1[89]\s*mm\b",),      # 19 mm is sold as 18 mm
            "25 mm": (r"\b2[45]\s*mm\b",),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
    ),
    Slot(
        name="sheet_size",
        label="Sheet size",
        question="Which sheet size?",
        priority=28,
        chips=("8 x 4 ft", "7 x 4 ft", "6 x 4 ft", "8 x 3 ft", "Not Sure"),
        synonyms={
            "8 x 4 ft": (r"\b8\s*[x×*]\s*4\b", r"\bfull\s*sheet\b", r"\b2440\b"),
            "7 x 4 ft": (r"\b7\s*[x×*]\s*4\b", r"\b2130\b"),
            "6 x 4 ft": (r"\b6\s*[x×*]\s*4\b", r"\b1830\b"),
            "8 x 3 ft": (r"\b8\s*[x×*]\s*3\b",),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b", r"\bstandard\b"),
        },
        grouping=True,
    ),
    Slot(
        name="core",
        label="Core",
        # Not asked, for the same reason as the grade: it is a question only a
        # timber trader enjoys. Still read when volunteered ("gurjan ply") and
        # passed to the supplier. It is not a grouping field, so nothing about
        # pricing or pooling depends on it.
        asked=False,
        question="Any preference on the core timber?",
        priority=32,
        chips=("Hardwood", "Gurjan", "Poplar", "Eucalyptus", "No Preference"),
        synonyms={
            "Gurjan": (r"\bgurjan\b", r"\bgurgan\b", r"\b100\s*%?\s*gurjan\b"),
            "Hardwood": (r"\bhard\s*wood\b", r"\bhardwood\b"),
            "Poplar": (r"\bpoplar\b", r"\bpopular\b"),
            "Eucalyptus": (r"\beucalyptus\b", r"\bsafeda\b"),
            "No Preference": (r"\bno\s*preference\b", r"\bany\b", r"\bnot\s*sure\b"),
        },
        required=False,
    ),
    Slot(
        name="finish",
        label="Finish",
        # Not asked either. Teak-faced and laminated boards do cost more than
        # plain, so this one is a real trade-off: the flow is shorter, and the
        # supplier quotes against the default unless the buyer says otherwise
        # ("one side teak"), which is still read.
        asked=False,
        question="What surface finish?",
        priority=34,
        chips=("Plain / unfinished", "One side teak", "Both sides teak", "Laminated",
               "No Preference"),
        synonyms={
            "Both sides teak": (r"\bboth\s*side", r"\bbst\b", r"\bdouble\s*side"),
            "One side teak": (r"\bone\s*side", r"\bost\b", r"\bsingle\s*side"),
            "Laminated": (r"\blaminat", r"\bpre[\s\-]?lam", r"\bsunmica\b"),
            "Plain / unfinished": (r"\bplain\b", r"\bunfinish", r"\bnormal\b", r"\braw\b"),
            "No Preference": (r"\bno\s*preference\b", r"\bany\b"),
        },
        required=False,
    ),
    Slot(
        name="preferred_brand",
        label="Preferred brand",
        question="Any preferred brand?",
        priority=36,
        chips=("Century", "Greenply", "Kitply", "Merino", "Archidply", "No Preference"),
        synonyms={
            "Century": (r"\bcentury\b", r"\bcenturyply\b", r"\bsentury\b"),
            "Greenply": (r"\bgreen\s*ply\b", r"\bgreenply\b", r"\bgreen\b"),
            "Kitply": (r"\bkit\s*ply\b", r"\bkitply\b"),
            "Merino": (r"\bmerino\b",),
            "Archidply": (r"\barchid\s*ply\b", r"\barchidply\b"),
            "Austin": (r"\baustin\b",),
            "Duro": (r"\bduro\b", r"\bduroply\b"),
            "National": (r"\bnational\b",),
            "Rushil": (r"\brushil\b",),
            "No Preference": (r"\bno\s*preference\b", r"\bany\s*brand\b", r"\bnot\s*fixed\b",
                              r"\blocal\b"),
        },
        freeform=True,
    ),
    Slot(
        name="brand_flexible",
        label="Brand flexibility",
        question=(
            "If another reliable brand gives the group a significantly better price, "
            "would you consider it?"
        ),
        priority=40,
        kind="bool",
        chips=("Yes", "{brand} Only"),
        synonyms={
            "yes": (r"\byes\b", r"\bsure\b", r"\bok(ay)?\b", r"\bopen\b", r"\bconsider\b",
                    r"\bhaan\b"),
            "no": (r"\bno\b", r"\bonly\b", r"\bstrictly\b", r"\bmust be\b", r"\bnahi\b"),
        },
        ask_if=lambda s: str(s.get("preferred_brand", "")).lower() not in ("", "no preference"),
    ),
    Slot(
        name="application",
        label="Application",
        # Useful to the supplier, but the engine asks a fixed number of
        # optional questions -- so leaving this one askable simply means it
        # takes the slot a removed question vacated, and the flow never
        # actually gets shorter. Read when volunteered, never asked.
        asked=False,
        question="What is it for?",
        priority=42,
        chips=("Furniture", "Interior / fit-out", "Kitchen", "Shuttering / construction",
               "Packaging", "Other"),
        synonyms={
            "Shuttering / construction": (r"\bshutter", r"\bcentering\b", r"\bconstruction\b",
                                          r"\bslab\b", r"\bcivil\b"),
            "Kitchen": (r"\bkitchen\b", r"\bmodular\b", r"\bcabinet\b"),
            "Furniture": (r"\bfurniture\b", r"\bwardrobe\b", r"\bbed\b", r"\btable\b",
                          r"\bsofa\b", r"\bcarpent"),
            "Interior / fit-out": (r"\binterior\b", r"\bfit[\s\-]?out\b", r"\bfalse\s*ceiling\b",
                                   r"\bpartition\b", r"\bpanel"),
            "Packaging": (r"\bpackag", r"\bcrate\b", r"\bbox(es)?\b", r"\bpallet\b"),
            "Other": (r"\bother\b", r"\bmisc", r"\bnot\s*sure\b"),
        },
        required=False,
    ),
    Slot(
        name="isi_marked",
        label="ISI marked",
        # Useful to the supplier, but the engine asks a fixed number of
        # optional questions -- so leaving this one askable simply means it
        # takes the slot a removed question vacated, and the flow never
        # actually gets shorter. Read when volunteered, never asked.
        asked=False,
        question="Do you need ISI-marked (BIS certified) sheets?",
        priority=56,
        kind="bool",
        chips=("Yes, ISI marked", "Not required"),
        synonyms={
            "yes": (r"\byes\b", r"\bisi\b", r"\bbis\b", r"\bcertified\b", r"\brequired\b",
                    r"\bmarked\b"),
            "no": (r"\bno\b", r"\bnot\s*required\b", r"\bdoesn'?t matter\b", r"\bany\b"),
        },
        required=False,
    ),
    Slot(
        name="budget",
        label="Budget per sheet",
        # Useful to the supplier, but the engine asks a fixed number of
        # optional questions -- so leaving this one askable simply means it
        # takes the slot a removed question vacated, and the flow never
        # actually gets shorter. Read when volunteered, never asked.
        asked=False,
        question="Do you have a budget per sheet in mind? (optional)",
        priority=60,
        kind="number",
        chips=("Under ₹1,000", "₹1,000 - ₹2,000", "Above ₹2,000", "Skip"),
        required=False,
    ),
)

# Per-sheet reference prices for a full 8x4 ft sheet, before the volume ladder.
_BASE_8X4 = {
    ("MR", "6 mm"): 620, ("MR", "9 mm"): 850, ("MR", "12 mm"): 1150,
    ("MR", "16 mm"): 1450, ("MR", "18 mm"): 1650, ("MR", "25 mm"): 2250,
    ("BWR", "6 mm"): 780, ("BWR", "9 mm"): 1050, ("BWR", "12 mm"): 1420,
    ("BWR", "16 mm"): 1780, ("BWR", "18 mm"): 2050, ("BWR", "25 mm"): 2800,
    ("BWP Marine", "12 mm"): 1850, ("BWP Marine", "18 mm"): 2650,
    ("BWP Marine", "25 mm"): 3550,
    ("Fire Retardant", "12 mm"): 2100, ("Fire Retardant", "18 mm"): 2900,
}

#: Smaller sheets are priced off area, near enough for an indicative slab.
_SIZE_FACTOR = {"8 x 4 ft": 1.00, "7 x 4 ft": 0.88, "6 x 4 ft": 0.76, "8 x 3 ft": 0.76}


def _key(grade: str, thickness: str, size: str) -> str:
    parts = [p.strip().lower().replace(" ", "_") for p in (grade, thickness, size)]
    return "PLY|" + "|".join(parts)


PLYWOOD_SLABS: dict[str, tuple[Slab, ...]] = {
    _key(grade, thickness, size): ladder(base * factor)
    for (grade, thickness), base in _BASE_8X4.items()
    for size, factor in _SIZE_FACTOR.items()
}

CATEGORY = Category(
    key="PLY",
    label="Plywood",
    plural_label="plywood",
    emoji="🪵",
    unit="sheet",
    unit_plural="sheets",
    quantity_question="How many sheets do you need?",
    quantity_chips=("10", "25", "50", "100", "250", "500+"),
    # After the specification, before location: "how many sheets?" only means
    # something once grade, thickness and size are settled.
    quantity_priority=44,
    slots=PLYWOOD_SLOTS,
    grouping_fields=("grade", "thickness", "sheet_size"),
    slabs=PLYWOOD_SLABS,
    default_slab_key="PLY|mr|12_mm|8_x_4_ft",
    grouping_defaults={"grade": "MR", "thickness": "12 mm", "sheet_size": "8 x 4 ft"},
    triggers=(
        r"\bply\s*wood\b", r"\bplywood\b", r"\bply\b", r"\bmarine\s*ply\b",
        r"\bcommercial\s*ply\b", r"\bblock\s*board\b", r"\bshuttering\s*ply\b",
    ),
    # Board products that are not plywood: different material, different price
    # basis. They pool in the open-ended flow and wait for a real quote.
    exclusions=(
        r"\bmdf\b", r"\bhdf\b", r"\bparticle\s*board\b", r"\bwpc\b", r"\bpvc\b",
        r"\bveneer\b", r"\blaminate\s*sheet\b", r"\bsunmica\s*sheet\b",
        r"\bacrylic\b", r"\bflush\s*door\b",
    ),
    # A number is a quantity only when it is not a spec figure (mm / ft / x).
    quantity_patterns=(
        (
            r"\b(\d{1,5})(?!\s*(?:mm|ft|feet|inch|[x×*]|\s*[x×*]))"
            r"(?:\s+[\w\.\-]+){0,4}?\s*(?:sheets?|nos?|pieces?|pcs?|ply\w*)\b",
            1.0,
        ),
        (r"\b(\d{1,5})\s*sheets?\b", 1.0),
    ),
    # Name the product in the label, not the counting unit ("... 8 x 4 ft sheet").
    product_noun="Plywood",
    addons=PLYWOOD_ADDONS,
    addon_prompt=(
        "One last thing 👇\n\n"
        "Most plywood buyers need a few of these in the same order. "
        "Adding them costs nothing now — we'll ask the supplier to quote them "
        "with the board, so the group gets a better rate on those too."
    ),
    min_group_quantity=10,
    brand_field="preferred_brand",
    intro=(
        "Plywood is bought by the sheet and discounts hard by volume — pooling "
        "a few orders moves the price meaningfully."
    ),
)
