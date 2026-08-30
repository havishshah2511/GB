"""Rooftop solar subsidy under PM Surya Ghar Muft Bijli Yojana.

Every figure here is a backend constant, exactly like a price slab: the
language layer may echo what this returns and must never compute a subsidy
itself. Getting it wrong costs a customer real money.

The scheme, as verified August 2026:

  Residential      ₹30,000/kW for the first 2 kW, ₹18,000 for the third,
                   capped at ₹78,000. A 3 kW system reaches the cap, so
                   anything larger receives the same ₹78,000.
  Housing society  ₹18,000/kW for common facilities, up to 500 kW.
  Commercial /
  industrial /
  institutional    NOT ELIGIBLE. No central subsidy exists for them under this
                   scheme; accelerated depreciation is the usual benefit
                   instead. Saying otherwise would mislead a buyer into
                   budgeting for money that will never arrive.

Conditions that decide whether a subsidy actually lands: grid-connected
rooftop, DCR (domestic content) modules, an empanelled vendor, a DISCOM
inspection, and a national portal application. The bot states the amount as
indicative and says so.

Some special-category states top this up (reported up to ₹1,17,000). That
varies by state and is deliberately not computed -- an operator confirms it.

Update RATES when the scheme changes; `test_subsidy.py` pins the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEME = "PM Surya Ghar Muft Bijli Yojana"
VERIFIED_ON = "2026-08-24"

#: Residential slab: (up to kW, rupees per kW within this band).
RESIDENTIAL_BANDS: tuple[tuple[float, int], ...] = ((2.0, 30000), (3.0, 18000))
RESIDENTIAL_CAP = 78000

#: Group housing society / RWA common facilities.
SOCIETY_RATE_PER_KW = 18000
SOCIETY_MAX_KW = 500

CONDITIONS = (
    "Grid-connected rooftop system",
    "DCR (domestic content) modules",
    "Vendor empanelled with your DISCOM",
    "Applied through the national portal, subject to DISCOM inspection",
)


@dataclass(frozen=True)
class Subsidy:
    eligible: bool
    amount: float
    consumer_type: str
    basis: str
    conditions: tuple[str, ...] = ()
    note: str = ""
    capped: bool = False
    #: kW that actually attracted subsidy (a 10 kW home system is paid on 3).
    subsidised_kw: float = 0.0
    alternatives: tuple[str, ...] = field(default_factory=tuple)


#: Which site types are treated as which kind of electricity consumer.
CONSUMER_BY_SITE = {
    "Home / residential": "residential",
    "Housing society": "society",
    "Factory": "commercial",
    "Warehouse": "commercial",
    "Office building": "commercial",
    "School / College": "institutional",
    "Hospital": "institutional",
}


def consumer_type_for(site_type: str | None) -> str | None:
    if not site_type:
        return None
    return CONSUMER_BY_SITE.get(str(site_type).strip())


def calculate(system_kw: float, consumer_type: str | None) -> Subsidy:
    """Central subsidy for a system of this size and consumer type."""
    kw = max(0.0, float(system_kw or 0))

    if consumer_type == "residential":
        amount = 0.0
        covered = 0.0
        previous = 0.0
        for ceiling, rate in RESIDENTIAL_BANDS:
            band = max(0.0, min(kw, ceiling) - previous)
            amount += band * rate
            covered += band
            previous = ceiling
        capped = amount >= RESIDENTIAL_CAP or kw > RESIDENTIAL_BANDS[-1][0]
        amount = min(amount, RESIDENTIAL_CAP)
        return Subsidy(
            eligible=amount > 0,
            amount=amount,
            consumer_type="residential",
            basis="₹30,000/kW for the first 2 kW, ₹18,000 for the third, capped at ₹78,000",
            conditions=CONDITIONS,
            capped=capped,
            subsidised_kw=min(covered, RESIDENTIAL_BANDS[-1][0]),
            note=(
                "The subsidy is capped at 3 kW, so a larger system receives the "
                "same ₹78,000 — the extra capacity is unsubsidised."
                if capped and kw > RESIDENTIAL_BANDS[-1][0] else ""
            ),
        )

    if consumer_type == "society":
        covered = min(kw, SOCIETY_MAX_KW)
        return Subsidy(
            eligible=covered > 0,
            amount=covered * SOCIETY_RATE_PER_KW,
            consumer_type="society",
            basis=f"₹{SOCIETY_RATE_PER_KW:,}/kW for common facilities, up to {SOCIETY_MAX_KW} kW",
            conditions=CONDITIONS,
            capped=kw > SOCIETY_MAX_KW,
            subsidised_kw=covered,
            note=(
                f"Only the first {SOCIETY_MAX_KW} kW attracts subsidy."
                if kw > SOCIETY_MAX_KW else ""
            ),
        )

    if consumer_type in ("commercial", "institutional"):
        return Subsidy(
            eligible=False,
            amount=0.0,
            consumer_type=consumer_type,
            basis=f"{SCHEME} is residential-only",
            note=(
                "Commercial, industrial and institutional connections do not "
                "receive a central subsidy under this scheme. Budget for the "
                "full system cost."
            ),
            alternatives=(
                "Accelerated depreciation (a tax benefit on the asset)",
                "Input tax credit on GST, where you are registered",
                "Some states run their own C&I incentives — worth checking locally",
            ),
        )

    return Subsidy(
        eligible=False, amount=0.0, consumer_type="unknown",
        basis="", note="Tell us the site type and we can check subsidy eligibility.",
    )


def to_card(subsidy: Subsidy, system_kw: float) -> dict:
    """Render-ready card. All numbers originate here, not in the language layer."""
    from ..utils import money

    card: dict = {
        "type": "subsidy",
        "scheme": SCHEME,
        "eligible": subsidy.eligible,
        "consumer_type": subsidy.consumer_type,
        "amount": subsidy.amount,
        "amount_text": money(subsidy.amount) if subsidy.amount else "",
        "basis": subsidy.basis,
        "note": subsidy.note,
        "conditions": list(subsidy.conditions),
        "alternatives": list(subsidy.alternatives),
        "system_kw": system_kw,
        "subsidised_kw": subsidy.subsidised_kw,
        # Never presented as guaranteed: eligibility is the DISCOM's call.
        "disclaimer": (
            "Indicative only — the final amount is confirmed by your DISCOM "
            "after inspection."
        ),
    }
    return card
