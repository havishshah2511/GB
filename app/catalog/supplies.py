"""Companion products: the supplies that leave the shop with a board order.

These are full categories, not notes on someone else's intent. A buyer who says
they need nails is asked what nails -- size and type -- because "nails" is not
a thing a supplier can quote. Once that is known the requirement pools with
every other buyer wanting the same nails in the same city, exactly like the
plywood itself, and gets its own group and its own code.

They are `addon_only`, so they never appear in the opening menu: you reach them
by picking them alongside a main order. And they ship with **no price slabs** --
nobody has quoted for them yet, so their groups collect quantity and say so.
The operator loads real slabs once a supplier comes back.

Two grouping fields each, deliberately. One is not enough to quote from; three
turns a helpful add-on into an interrogation and splits the pool so finely that
nothing ever reaches a volume worth negotiating.
"""
from __future__ import annotations

from .base import Category, Slot

#: Every companion category, in the order plywood offers them.
KEYS = ("ADHESIVE", "NAILS", "SCREWS", "FITTINGS", "LAMINATE", "EDGEBAND")

_NOT_SURE = (r"\bnot\s*sure\b", r"\bany\b", r"\bno\s*idea\b", r"\bdon'?t\s*know\b",
             r"\bwhatever\b", r"\bkoi\s*bhi\b", r"\bsuggest\b")


def _qty(unit: str, *words: str) -> tuple[tuple[str, float], ...]:
    """Read "5 kg", "10 boxes", "200 pieces" as a quantity for this unit."""
    alternatives = "|".join(words)
    return ((rf"\b(\d{{1,6}}(?:\.\d+)?)\s*(?:{alternatives})\b", 1.0),)


def _inches(number: str) -> str:
    """A length in inches, however it is written: 2 inch, 2in, 2", 2'."""
    return rf"\b{number}\s*(?:inches|inch|in\b|\"|'')"


# --------------------------------------------------------------------------- #
# adhesive -- Fevicol and friends
# --------------------------------------------------------------------------- #
ADHESIVE = Category(
    key="ADHESIVE",
    # Named for the brand every carpenter says out loud. It is an example, not
    # a commitment: the flow still asks which brand and the group is quoted on
    # whatever it actually buys.
    label="Adhesive (Fevicol)",
    plural_label="adhesive",
    emoji="🧴",
    unit="kg",
    unit_plural="kg",
    quantity_question="How much adhesive do you need, in kg?",
    quantity_chips=("1", "5", "10", "20", "50"),
    quantity_priority=44,
    slots=(
        Slot(
            name="adhesive_type",
            label="Type",
            question=(
                "Which adhesive?\n\n"
                "White glue is the everyday carpentry one, synthetic resin holds "
                "under load, rubber-based is for laminate and sunmica."
            ),
            priority=20,
            chips=("White glue", "Synthetic resin", "Rubber-based", "Epoxy", "Not Sure"),
            # "SR 998" is Fevicol's rubber-based contact adhesive, not a
            # synthetic resin, so it is claimed first -- "synthetic resin"
            # itself has no "sr" word in it and still lands correctly.
            synonyms={
                "White glue": (r"\bwhite\b", r"\bpva\b", r"\bsh\b", r"\bfevicol\s*sh\b",
                               r"\bwood\s*glue\b", r"\bsafed\b"),
                "Rubber-based": (r"\brubber\b", r"\bcontact\b", r"\bsr\b", r"\b998\b",
                                 r"\bneoprene\b", r"\blaminate\s*glue\b", r"\bsunmica\s*glue\b"),
                "Synthetic resin": (r"\bsynthetic\b", r"\bresin\b", r"\bmarine\b",
                                    r"\bwaterproof\b", r"\bheatx\b", r"\bwaterproofing\b"),
                "Epoxy": (r"\bepoxy\b", r"\baraldite\b", r"\btwo\s*part\b", r"\b2\s*part\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="pack_size",
            label="Pack size",
            question="Which pack size suits you? Bigger packs price better per kg.",
            priority=24,
            chips=("500 g", "1 kg", "5 kg", "20 kg", "50 kg", "Not Sure"),
            synonyms={
                "500 g": (r"\b500\s*(g|gm|gms|gram)", r"\bhalf\s*kg\b", r"\b0\.5\s*kg\b"),
                "1 kg": (r"\b1\s*kg\b", r"\bone\s*kg\b", r"\bek\s*kilo\b"),
                "5 kg": (r"\b5\s*kg\b", r"\bpanch\s*kilo\b"),
                "20 kg": (r"\b20\s*kg\b", r"\bbucket\b", r"\bdrum\b"),
                "50 kg": (r"\b50\s*kg\b", r"\bbig\s*drum\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="adhesive_brand",
            label="Preferred brand",
            question="Any brand you usually buy?",
            priority=30,
            # Fevicol is Pidilite's, so listing both would be the same answer
            # twice. The rest are the brands a dealer actually stocks beside it.
            chips=("Fevicol", "Astral Resibond", "Euro 7000", "Jubilant",
                   "No Preference"),
            synonyms={
                "Fevicol": (r"\bfevicol\b", r"\bfevi\b", r"\bpidilite\b"),
                "Astral Resibond": (r"\bastral\b", r"\bresibond\b"),
                "Euro 7000": (r"\beuro\s*7000\b", r"\beuro\b"),
                "Jubilant": (r"\bjubilant\b", r"\bjivanjor\b"),
                "No Preference": (r"\bno\s*preference\b", r"\bany\b", r"\blocal\b"),
            },
            required=False,
            freeform=True,
        ),
    ),
    grouping_fields=("adhesive_type", "pack_size"),
    grouping_defaults={"adhesive_type": "White glue", "pack_size": "5 kg"},
    slabs={},
    default_slab_key="",
    quantity_patterns=_qty("kg", "kgs?", "kilos?", "tins?", "buckets?", "packs?"),
    triggers=(r"\bfevicol\b", r"\badhesive\b", r"\bglue\b", r"\bgond\b",
              r"\bsr\s*998\b"),
    product_noun="Adhesive",
    brand_field="adhesive_brand",
    min_group_quantity=5,
    intro="Let's pin down the adhesive 🧴",
)

# --------------------------------------------------------------------------- #
# nails -- the example the brief asked for
# --------------------------------------------------------------------------- #
NAILS = Category(
    key="NAILS",
    label="Nails & pins",
    plural_label="nails",
    emoji="📌",
    unit="kg",
    unit_plural="kg",
    quantity_question="How many kg of nails?",
    quantity_chips=("1", "2", "5", "10", "25"),
    quantity_priority=44,
    slots=(
        Slot(
            name="nail_size",
            label="Size",
            question=(
                "What size nails?\n\n"
                "Length in inches — it's the first thing a supplier asks."
            ),
            priority=20,
            chips=("1 inch", "1.5 inch", "2 inch", "2.5 inch", "3 inch", "4 inch", "Mixed"),
            # A trailing \b would never match after a quote mark, so the inch
            # symbol gets its own alternative: 1.5" is how people write it.
            synonyms={
                "1.5 inch": (_inches("1\\.5"), r"\b1\s*1/2\b", r"\bderh\s*inch\b",
                             r"\b40\s*mm\b"),
                "2.5 inch": (_inches("2\\.5"), r"\b2\s*1/2\b", r"\b65\s*mm\b"),
                "1 inch": (_inches("1"), r"\b25\s*mm\b", r"\bek\s*inch\b"),
                "2 inch": (_inches("2"), r"\b50\s*mm\b", r"\bdo\s*inch\b"),
                "3 inch": (_inches("3"), r"\b75\s*mm\b", r"\bteen\s*inch\b"),
                "4 inch": (_inches("4"), r"\b100\s*mm\b"),
                "Mixed": (r"\bmix", r"\bassort", r"\bdifferent\s*size", r"\ball\s*size",
                          r"\bvariety\b") + _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="nail_type",
            label="Type",
            question=(
                "Which type?\n\n"
                "Wire nails are the common ones, panel pins are thin and headless "
                "for beading, brads go in a nail gun."
            ),
            priority=24,
            chips=("Wire", "Panel pin", "Brad", "Concrete", "U-nail", "Not Sure"),
            synonyms={
                "Wire": (r"\bwire\b", r"\bcommon\b", r"\bnormal\b", r"\bkeel\b", r"\bsadharan\b"),
                "Panel pin": (r"\bpanel\s*pin", r"\bpin\b", r"\bpins\b", r"\bheadless\b",
                              r"\bbeading\s*nail"),
                "Brad": (r"\bbrad\b", r"\bnail\s*gun\b", r"\bpneumatic\b", r"\bf\s*30\b",
                         r"\bstaple"),
                "Concrete": (r"\bconcrete\b", r"\bmasonry\b", r"\bwall\s*nail", r"\bsteel\s*nail"),
                "U-nail": (r"\bu\s*nail", r"\bstaple\s*nail", r"\bfencing\b", r"\bclip\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="nail_finish",
            label="Finish",
            question="Plain steel is fine for indoor work — or do you need galvanised?",
            priority=30,
            chips=("Plain / MS", "Galvanised", "Stainless", "No Preference"),
            synonyms={
                "Galvanised": (r"\bgalvani", r"\bgi\b", r"\bzinc\b", r"\bouter\b", r"\bexterior\b",
                               r"\brust\s*proof\b"),
                "Stainless": (r"\bstainless\b", r"\bss\b", r"\b304\b"),
                "Plain / MS": (r"\bplain\b", r"\bms\b", r"\bmild\s*steel\b", r"\bnormal\b",
                               r"\bindoor\b"),
                "No Preference": (r"\bno\s*preference\b", r"\bany\b"),
            },
            required=False,
        ),
    ),
    grouping_fields=("nail_size", "nail_type"),
    grouping_defaults={"nail_size": "2 inch", "nail_type": "Wire"},
    slabs={},
    default_slab_key="",
    quantity_patterns=_qty("kg", "kgs?", "kilos?", "packets?", "boxes?"),
    triggers=(r"\bnails?\b", r"\bpanel\s*pins?\b", r"\bkeel\b", r"\bbrad\b"),
    product_noun="Nails",
    min_group_quantity=5,
    intro="Now the nails 📌",
)

# --------------------------------------------------------------------------- #
# screws
# --------------------------------------------------------------------------- #
SCREWS = Category(
    key="SCREWS",
    label="Screws",
    plural_label="screws",
    emoji="🔩",
    unit="box",
    unit_plural="boxes",
    addon_only=True,
    quantity_question="How many boxes of screws? (a box is usually 100 or 200 pieces)",
    quantity_chips=("1", "2", "5", "10", "25"),
    quantity_priority=44,
    slots=(
        Slot(
            name="screw_size",
            label="Size",
            question="What size screws? Gauge × length is how they're sold.",
            priority=20,
            chips=("6 x 1 inch", "8 x 1.5 inch", "8 x 2 inch", "10 x 2.5 inch",
                   "10 x 3 inch", "Mixed"),
            synonyms={
                "6 x 1 inch": (r"\b6\s*[x×*]\s*1\b", r"\b6\s*gauge\b"),
                "8 x 1.5 inch": (r"\b8\s*[x×*]\s*1\.5\b", r"\b8\s*[x×*]\s*1\s*1/2\b"),
                "8 x 2 inch": (r"\b8\s*[x×*]\s*2\b",),
                "10 x 2.5 inch": (r"\b10\s*[x×*]\s*2\.5\b",),
                "10 x 3 inch": (r"\b10\s*[x×*]\s*3\b",),
                "Mixed": (r"\bmix", r"\bassort", r"\ball\s*size") + _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="screw_type",
            label="Type",
            question="Which type?",
            priority=24,
            chips=("Wood", "Self-tapping", "Drywall", "Stainless", "Not Sure"),
            synonyms={
                "Wood": (r"\bwood\b", r"\blakdi\b", r"\bcsk\b", r"\bcountersunk\b"),
                "Self-tapping": (r"\bself\s*tap", r"\bst\b", r"\bsheet\s*metal\b"),
                "Drywall": (r"\bdry\s*wall\b", r"\bgypsum\b", r"\bboard\s*screw\b"),
                "Stainless": (r"\bstainless\b", r"\bss\b", r"\b304\b", r"\bouter\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
    ),
    grouping_fields=("screw_size", "screw_type"),
    grouping_defaults={"screw_size": "8 x 2 inch", "screw_type": "Wood"},
    slabs={},
    default_slab_key="",
    quantity_patterns=_qty("box", "boxes?", "packets?", "packs?"),
    product_noun="Screws",
    min_group_quantity=2,
    intro="And the screws 🔩",
)

# --------------------------------------------------------------------------- #
# hinges, channels, handles, locks
# --------------------------------------------------------------------------- #
FITTINGS = Category(
    key="FITTINGS",
    label="Hinges & fittings",
    plural_label="fittings",
    emoji="🚪",
    unit="piece",
    unit_plural="pieces",
    addon_only=True,
    quantity_question="How many pieces?",
    quantity_chips=("10", "25", "50", "100", "250"),
    quantity_priority=44,
    slots=(
        Slot(
            name="fitting_finish",
            label="Material / finish",
            question="Which material?",
            priority=20,
            chips=("Stainless steel", "Mild steel", "Brass", "Powder coated", "Not Sure"),
            synonyms={
                "Stainless steel": (r"\bstainless\b", r"\bss\b", r"\b304\b", r"\b202\b"),
                "Mild steel": (r"\bmild\s*steel\b", r"\bms\b", r"\biron\b", r"\bloha\b"),
                "Brass": (r"\bbrass\b", r"\bpeetal\b", r"\bantique\b"),
                "Powder coated": (r"\bpowder\b", r"\bcoated\b", r"\bmatte?\s*black\b",
                                  r"\bpainted\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="fitting_type",
            label="Item",
            question="Which fitting do you need most of?",
            priority=24,
            chips=("Butt hinge", "Soft-close hinge", "Telescopic channel", "Drawer slide",
                   "Handle", "Lock"),
            synonyms={
                "Soft-close hinge": (r"\bsoft\s*clos", r"\bauto\s*hinge\b", r"\bhydraulic\b",
                                     r"\bconceal"),
                "Butt hinge": (r"\bbutt\b", r"\bhinge\b", r"\bkabza\b", r"\bkabja\b",
                               r"\bpiano\s*hinge\b"),
                "Telescopic channel": (r"\btelescop", r"\bchannel\b", r"\bball\s*bearing\b"),
                "Drawer slide": (r"\bdrawer\b", r"\bslide\b", r"\btandem\b"),
                "Handle": (r"\bhandle\b", r"\bknob\b", r"\bpull\b", r"\bhatthi\b"),
                "Lock": (r"\block\b", r"\blatch\b", r"\btala\b", r"\bcam\s*lock\b"),
            },
            grouping=True,
        ),
    ),
    grouping_fields=("fitting_finish", "fitting_type"),
    grouping_defaults={"fitting_finish": "Stainless steel", "fitting_type": "Butt hinge"},
    slabs={},
    default_slab_key="",
    quantity_patterns=_qty("piece", "pieces?", "pcs?", "nos?", "sets?", "pairs?"),
    product_noun="Fittings",
    min_group_quantity=10,
    intro="Let's get the fittings right 🚪",
)

# --------------------------------------------------------------------------- #
# decorative laminate
# --------------------------------------------------------------------------- #
LAMINATE = Category(
    key="LAMINATE",
    label="Laminate / sunmica",
    plural_label="laminate",
    emoji="🎨",
    unit="sheet",
    unit_plural="sheets",
    addon_only=True,
    quantity_question="How many laminate sheets?",
    quantity_chips=("5", "10", "25", "50", "100"),
    quantity_priority=44,
    slots=(
        Slot(
            name="laminate_thickness",
            label="Thickness",
            question=(
                "What thickness?\n\n"
                "0.8 mm is the usual interior sheet, 1 mm and above for high-wear surfaces."
            ),
            priority=20,
            chips=("0.8 mm", "1 mm", "1.5 mm", "Not Sure"),
            synonyms={
                "0.8 mm": (r"\b0?\.8\s*mm\b", r"\b8\s*mm\s*lam", r"\bnormal\b", r"\bregular\b"),
                "1 mm": (r"\b1\s*mm\b", r"\b1\.0\s*mm\b"),
                "1.5 mm": (r"\b1\.5\s*mm\b", r"\bcompact\b", r"\bthick\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="laminate_finish",
            label="Finish",
            question="Which finish?",
            priority=24,
            chips=("Glossy", "Matte", "Textured", "Suede", "Not Sure"),
            synonyms={
                "Glossy": (r"\bgloss", r"\bhigh\s*gloss\b", r"\bshiny\b", r"\bchamak"),
                "Matte": (r"\bmatte?\b", r"\bmat\b", r"\bsuede\s*matt\b"),
                "Textured": (r"\btextur", r"\bwood\s*grain\b", r"\bembos"),
                "Suede": (r"\bsuede\b", r"\bsoft\s*touch\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="laminate_brand",
            label="Preferred brand",
            question="Any brand in mind?",
            priority=30,
            chips=("Merino", "Greenlam", "Century", "Royale Touche", "No Preference"),
            synonyms={
                "Merino": (r"\bmerino\b",),
                "Greenlam": (r"\bgreen\s*lam\b", r"\bgreenlam\b"),
                "Century": (r"\bcentury\b", r"\bcenturylam\b"),
                "Royale Touche": (r"\broyale?\b", r"\btouche\b"),
                "No Preference": (r"\bno\s*preference\b", r"\bany\b", r"\blocal\b"),
            },
            required=False,
            freeform=True,
        ),
    ),
    grouping_fields=("laminate_thickness", "laminate_finish"),
    grouping_defaults={"laminate_thickness": "0.8 mm", "laminate_finish": "Matte"},
    slabs={},
    default_slab_key="",
    quantity_patterns=_qty("sheet", "sheets?", "nos?", "pcs?", "pieces?"),
    product_noun="Laminate",
    brand_field="laminate_brand",
    min_group_quantity=5,
    intro="Now the laminate 🎨",
)

# --------------------------------------------------------------------------- #
# edge banding
# --------------------------------------------------------------------------- #
EDGEBAND = Category(
    key="EDGEBAND",
    label="Edge banding tape",
    plural_label="edge banding",
    emoji="🎗️",
    unit="roll",
    unit_plural="rolls",
    addon_only=True,
    quantity_question="How many rolls? (a roll is usually 50 metres)",
    quantity_chips=("1", "2", "5", "10", "25"),
    quantity_priority=44,
    slots=(
        Slot(
            name="band_width",
            label="Width",
            question="What width? It should match the board edge — 19 mm and 22 mm are standard.",
            priority=20,
            chips=("19 mm", "22 mm", "25 mm", "45 mm", "Mixed"),
            synonyms={
                "19 mm": (r"\b19\s*mm\b", r"\b18\s*mm\b"),
                "22 mm": (r"\b22\s*mm\b", r"\b21\s*mm\b"),
                "25 mm": (r"\b25\s*mm\b",),
                "45 mm": (r"\b4[05]\s*mm\b",),
                "Mixed": (r"\bmix", r"\bassort") + _NOT_SURE,
            },
            grouping=True,
        ),
        Slot(
            name="band_material",
            label="Material",
            question="Which material?",
            priority=24,
            chips=("PVC", "ABS", "Acrylic", "Wood veneer", "Not Sure"),
            synonyms={
                "PVC": (r"\bpvc\b", r"\bnormal\b", r"\bregular\b"),
                "ABS": (r"\babs\b",),
                "Acrylic": (r"\bacrylic\b", r"\bglossy\s*band\b", r"\b3d\b"),
                "Wood veneer": (r"\bveneer\b", r"\bwood\s*band\b", r"\breal\s*wood\b"),
                "Not Sure": _NOT_SURE,
            },
            grouping=True,
        ),
    ),
    grouping_fields=("band_width", "band_material"),
    grouping_defaults={"band_width": "22 mm", "band_material": "PVC"},
    slabs={},
    default_slab_key="",
    quantity_patterns=_qty("roll", "rolls?", "metres?", "meters?", "mtrs?"),
    product_noun="Edge Band",
    min_group_quantity=2,
    intro="Last one — the edge banding 🎗️",
)

CATEGORIES = (ADHESIVE, NAILS, SCREWS, FITTINGS, LAMINATE, EDGEBAND)
