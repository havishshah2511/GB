"""Commercial solar panels.

The brief scores this family 10/10, and it is the clearest case for pooling:
module prices move sharply with volume and the buyers (factories, warehouses,
societies) are fragmented.

**Counted in kW, not panels.** Commercial solar is quoted per watt-peak, and a
"500 W panel" from one supplier is a different unit of value from a 550 W one.
Asking for system size in kW is how the customer already thinks about it and is
what a supplier quotes against, so a group of 250 kW means the same thing to
everyone in it.

Scope is part of the group because supply-only and full EPC (supply, structure,
cabling, installation, commissioning) are roughly half and double of each other
-- pooling them would price both wrongly.
"""
from __future__ import annotations

from .base import Category, Slab, Slot

SOLAR_SLOTS = (
    Slot(
        name="module_type",
        label="Module technology",
        question="Which module technology?",
        priority=20,
        chips=("Mono PERC", "TOPCon", "Bifacial", "Polycrystalline", "Not Sure"),
        synonyms={
            "TOPCon": (r"\btopcon\b", r"\btop\s*con\b", r"\bn[\s\-]?type\b"),
            "Bifacial": (r"\bbi[\s\-]?facial\b", r"\bdouble\s*glass\b"),
            "Mono PERC": (r"\bmono\s*perc\b", r"\bmonoperc\b", r"\bperc\b", r"\bmono\b",
                          r"\bmonocrystalline\b"),
            "Polycrystalline": (r"\bpoly\b", r"\bpolycrystalline\b", r"\bmulti\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bno\s*idea\b", r"\bdon'?t\s*know\b",
                         r"\bsuggest\b", r"\brecommend\b"),
        },
        grouping=True,
    ),
    Slot(
        name="scope",
        label="Scope",
        question=(
            "Do you need panels only, or a complete installed system?\n\n"
            "A complete system includes structure, cabling, inverter and commissioning."
        ),
        priority=25,
        chips=("Panels only", "Installed system", "Not Sure"),
        synonyms={
            "Installed system": (
                r"\bcomplete\b", r"\binstall", r"\bepc\b", r"\bturnkey\b",
                r"\bfull\s*system\b", r"\bend\s*to\s*end\b", r"\bcommission",
                r"\bwith\s*structure\b",
            ),
            "Panels only": (
                r"\bpanels?\s*only\b", r"\bsupply\s*only\b", r"\bonly\s*panels?\b",
                r"\bmodules?\s*only\b", r"\bjust\s*(the\s*)?panels?\b", r"\bsupply\b",
            ),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b", r"\bdon'?t\s*know\b"),
        },
        grouping=True,
    ),
    Slot(
        name="mounting",
        label="Mounting",
        question="Where will it be installed?",
        priority=30,
        chips=("Rooftop", "Ground mount", "Carport", "Not Sure"),
        synonyms={
            "Ground mount": (r"\bground\b", r"\bopen\s*land\b", r"\bfield\b", r"\bfarm\b"),
            "Carport": (r"\bcar\s*port\b", r"\bcarport\b", r"\bparking\b", r"\bshed\b"),
            "Rooftop": (r"\broof\s*top\b", r"\brooftop\b", r"\broof\b", r"\bterrace\b",
                        r"\bfactory\s*roof\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b"),
        },
        grouping=True,
    ),
    Slot(
        name="panel_wattage",
        label="Panel wattage",
        question="Any preferred panel wattage?",
        priority=33,
        chips=("400-450 Wp", "500-550 Wp", "550-600 Wp", "600 Wp+", "No Preference"),
        synonyms={
            "400-450 Wp": (r"\b4[0-5]\d\s*(?:w|wp|watt)\b",),
            "500-550 Wp": (r"\b5[0-4]\d\s*(?:w|wp|watt)\b", r"\b550\s*(?:w|wp|watt)\b"),
            "550-600 Wp": (r"\b5[6-9]\d\s*(?:w|wp|watt)\b",),
            "600 Wp+": (r"\b[6-9]\d\d\s*(?:w|wp|watt)\b", r"\b600\s*\+"),
            "No Preference": (r"\bno\s*preference\b", r"\bany\b", r"\bnot\s*sure\b"),
        },
        required=False,
    ),
    Slot(
        name="preferred_brand",
        label="Preferred brand",
        question="Any preferred module brand?",
        priority=35,
        chips=("Waaree", "Adani", "Vikram Solar", "Tata Power Solar", "Premier", "No Preference"),
        synonyms={
            "Waaree": (r"\bwaaree\b", r"\bwaree\b"),
            "Adani": (r"\badani\b",),
            "Vikram Solar": (r"\bvikram\b",),
            "Tata Power Solar": (r"\btata\b",),
            "Premier": (r"\bpremier\b",),
            "RenewSys": (r"\brenewsys\b", r"\brenew\s*sys\b"),
            "Goldi": (r"\bgoldi\b",),
            "Saatvik": (r"\bsaatvik\b",),
            "Jinko": (r"\bjinko\b",),
            "Longi": (r"\blongi\b",),
            "No Preference": (r"\bno\s*preference\b", r"\bany\s*brand\b", r"\bnot\s*fixed\b"),
        },
        freeform=True,
    ),
    Slot(
        name="brand_flexible",
        label="Brand flexibility",
        question=(
            "If another tier-1 brand gives the group a significantly better price, "
            "would you consider it?"
        ),
        priority=40,
        kind="bool",
        chips=("Yes", "{brand} Only"),
        synonyms={
            "yes": (r"\byes\b", r"\bsure\b", r"\bok(ay)?\b", r"\bopen\b", r"\bconsider\b",
                    r"\bhaan\b", r"\btier\s*1\b"),
            "no": (r"\bno\b", r"\bonly\b", r"\bstrictly\b", r"\bmust be\b", r"\bnahi\b"),
        },
        ask_if=lambda s: str(s.get("preferred_brand", "")).lower() not in ("", "no preference"),
    ),
    Slot(
        name="site_type",
        label="Site",
        question=(
            "What kind of site is this for?\n\n"
            "This decides which government subsidy you qualify for."
        ),
        # Sits where star rating does on the appliance flows: after brand.
        priority=42,
        chips=("Home / residential", "Housing society", "Factory", "Warehouse",
               "Office building", "School / College", "Hospital"),
        synonyms={
            # Society before residential: "residential society" is a society.
            "Housing society": (r"\bsociety\b", r"\bapartment\b", r"\bhousing\b",
                                r"\bflats?\b", r"\brwa\b", r"\bcomplex\b"),
            "Home / residential": (r"\bhome\b", r"\bhouse\b", r"\bresidential\b",
                                   r"\bghar\b", r"\bbungalow\b", r"\bvilla\b",
                                   r"\bindividual\b", r"\bmy\s*roof\b"),
            "Factory": (r"\bfactory\b", r"\bplant\b", r"\bindustr", r"\bmanufactur",
                        r"\bmill\b", r"\bunit\b"),
            "Warehouse": (r"\bwarehouse\b", r"\bgodown\b", r"\bstorage\b", r"\blogistic"),
            "Office building": (r"\boffice\b", r"\bcommercial\s*building\b", r"\bit\s*park\b"),
            "School / College": (r"\bschool\b", r"\bcollege\b", r"\buniversity\b",
                                 r"\binstitut", r"\bcampus\b"),
            "Hospital": (r"\bhospital\b", r"\bclinic\b", r"\bnursing\s*home\b"),
        },
        # Required: subsidy eligibility turns entirely on this answer, and a
        # wrong guess would have someone budgeting for money that never comes.
        required=True,
    ),
    Slot(
        name="dcr",
        label="DCR requirement",
        question=(
            "Do you need DCR modules?\n\n"
            "DCR (domestic content) modules are required for some government subsidies."
        ),
        priority=56,
        chips=("DCR required", "Non-DCR is fine", "Not Sure"),
        synonyms={
            "DCR required": (r"\bdcr\b(?!\s*not)", r"\bdomestic\b", r"\bsubsidy\b",
                             r"\bpm\s*surya\b", r"\bgovernment\b"),
            "Non-DCR is fine": (r"\bnon[\s\-]?dcr\b", r"\bno\s*dcr\b", r"\bimported\b",
                                r"\bnot\s*required\b"),
            "Not Sure": (r"\bnot\s*sure\b", r"\bany\b", r"\bdon'?t\s*know\b"),
        },
        required=False,
    ),
    Slot(
        name="budget",
        label="Budget per kW",
        question="Do you have a budget per kW in mind? (optional)",
        priority=60,
        kind="number",
        chips=("Under ₹25,000", "₹25,000 - ₹45,000", "Above ₹45,000", "Skip"),
        required=False,
    ),
)

# Prices are per kW of capacity. Slab 1 is the "regular price" shown
# struck-through. Panels-only tables are module supply; complete-system tables
# include structure, cabling, inverter, installation and commissioning.
SOLAR_SLABS: dict[str, tuple[Slab, ...]] = {
    # ---- panels only (mounting does not change a module price) -------------
    "SOLAR|mono_perc|panels_only|any": (
        Slab(1, 25, 24000), Slab(26, 100, 23000), Slab(101, 250, 22000),
        Slab(251, 500, 21000), Slab(501, 1000, 20000), Slab(1001, None, 19000),
    ),
    "SOLAR|topcon|panels_only|any": (
        Slab(1, 25, 26000), Slab(26, 100, 25000), Slab(101, 250, 24000),
        Slab(251, 500, 23000), Slab(501, 1000, 22000), Slab(1001, None, 21000),
    ),
    "SOLAR|bifacial|panels_only|any": (
        Slab(1, 25, 27500), Slab(26, 100, 26400), Slab(101, 250, 25300),
        Slab(251, 500, 24200), Slab(501, 1000, 23100), Slab(1001, None, 22000),
    ),
    "SOLAR|polycrystalline|panels_only|any": (
        Slab(1, 25, 21000), Slab(26, 100, 20200), Slab(101, 250, 19400),
        Slab(251, 500, 18600), Slab(501, 1000, 17800), Slab(1001, None, 17000),
    ),
    # ---- complete installed system ----------------------------------------
    "SOLAR|mono_perc|installed_system|rooftop": (
        Slab(1, 25, 48000), Slab(26, 100, 45000), Slab(101, 250, 42000),
        Slab(251, 500, 40000), Slab(501, 1000, 38000), Slab(1001, None, 36000),
    ),
    "SOLAR|mono_perc|installed_system|ground_mount": (
        Slab(1, 25, 52000), Slab(26, 100, 48500), Slab(101, 250, 45500),
        Slab(251, 500, 43000), Slab(501, 1000, 41000), Slab(1001, None, 39000),
    ),
    "SOLAR|mono_perc|installed_system|carport": (
        Slab(1, 25, 58000), Slab(26, 100, 55000), Slab(101, 250, 52000),
        Slab(251, 500, 49500), Slab(501, 1000, 47000), Slab(1001, None, 45000),
    ),
    "SOLAR|topcon|installed_system|rooftop": (
        Slab(1, 25, 51000), Slab(26, 100, 47500), Slab(101, 250, 44500),
        Slab(251, 500, 42000), Slab(501, 1000, 40000), Slab(1001, None, 38000),
    ),
    "SOLAR|bifacial|installed_system|ground_mount": (
        Slab(1, 25, 55000), Slab(26, 100, 51500), Slab(101, 250, 48500),
        Slab(251, 500, 46000), Slab(501, 1000, 44000), Slab(1001, None, 42000),
    ),
}

def _subsidy_cards(state: dict, facts: dict) -> list[dict]:
    """The government subsidy this buyer can expect, if any.

    Only shown once we know the site type, because eligibility turns on it
    entirely — and for a commercial site the honest answer is "none", which is
    worth saying plainly rather than leaving them to assume otherwise.
    """
    from . import subsidy as scheme

    consumer = scheme.consumer_type_for(state.get("site_type"))
    if consumer is None:
        return []
    system_kw = float(state.get("quantity") or 0)
    if system_kw <= 0:
        return []
    return [scheme.to_card(scheme.calculate(system_kw, consumer), system_kw)]


CATEGORY = Category(
    key="SOLAR",
    label="Solar panels",
    emoji="☀️",
    # Capacity, not panel count: it is how the customer thinks and how a
    # supplier quotes. "kW" reads the same at any quantity.
    unit="kW",
    unit_plural="kW",
    quantity_question=(
        "What system size do you need, in kW?\n\n"
        "Roughly 1 kW needs about 60 sq ft of shade-free roof."
    ),
    quantity_chips=("3.3 kW", "5 kW", "10 kW", "25 kW", "50 kW", "100 kW", "250 kW+"),
    slots=SOLAR_SLOTS,
    grouping_fields=("module_type", "scope", "mounting"),
    slabs=SOLAR_SLABS,
    default_slab_key="SOLAR|mono_perc|panels_only|any",
    grouping_defaults={
        "module_type": "Mono PERC", "scope": "Panels only", "mounting": "Rooftop",
    },
    triggers=(
        r"\bsolar\b", r"\bpv\s*(?:panel|module|system|plant)?\b", r"\bphotovoltaic\b",
        r"\bmono\s*perc\b", r"\btopcon\b", r"\bbifacial\b", r"\brooftop\s*plant\b",
    ),
    # The solar family in the brief is much wider than modules. Everything else
    # in it is a different purchase with its own price basis, so it goes to the
    # open-ended flow and waits for a real quote rather than being priced per kW.
    exclusions=(
        r"\bwater\s*heater\b", r"\bgeyser\b", r"\bsolar\s*pump\b", r"\bstreet\s*light\b",
        r"\bsolar\s*light\b", r"\blantern\b", r"\binverter\b", r"\bbatter", r"\bcable\b",
        r"\bstructure\b", r"\btransformer\b", r"\bcharge\s*controller\b", r"\bdcdb\b",
        r"\bacdb\b", r"\bjunction\s*box\b", r"\bcell\b", r"\bmonitoring\b",
    ),
    # Capacity, in kW. MW is converted; a bare number is left for the question,
    # because "100 panels" is not a system size and guessing a panel wattage
    # would silently invent the quantity.
    quantity_patterns=(
        (r"(\d+(?:\.\d+)?)\s*(?:mw|mwp|megawatts?)\b", 1000.0),
        (r"(\d+(?:\.\d+)?)\s*(?:kw|kwp|kilowatts?)\b", 1.0),
    ),
    product_noun="Solar",
    extra_cards=lambda state, facts: _subsidy_cards(state, facts),
    min_group_quantity=3.3,
    brand_field="preferred_brand",
    intro=(
        "Solar is the strongest category for group buying — module prices move "
        "sharply with volume, so pooled demand is worth real money."
    ),
)
