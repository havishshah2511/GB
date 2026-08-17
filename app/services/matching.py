"""Intent matching engine.

Matching is scored, not boolean, so the admin can see *why* an intent landed in
a group. Hard constraints (category, city, product spec, purchase-window
overlap, brand lock) filter first; the score then ranks the survivors.

    score = 40 base
          + 20 product-spec exactness
          + 20 brand fit
          + 10 group momentum (how close it already is to the next price slab)
          +  5 same area
          +  5 window overlap quality

Momentum matters: when a buyer is compatible with two groups, joining the
larger one unlocks a better price sooner for everybody, so demand consolidates
instead of fragmenting.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .. import catalog
from ..config import settings
from ..db import loads, parse_date, query, today
from ..utils import overlap_days
from . import groups

BASE_SCORE = 40
SPEC_WEIGHT = 20
BRAND_WEIGHT = 20
MOMENTUM_WEIGHT = 10
AREA_WEIGHT = 5
WINDOW_WEIGHT = 5


def _window(intent: dict[str, Any]) -> tuple[date, date]:
    """The span of dates this buyer would accept.

    Starts at `earliest_purchase_date`, which is today for anyone who answered
    with a deadline ("within 15 days") rather than a fixed date. Using the
    desired date as the start would put a "within 7 days" buyer and a "within
    15 days" buyer in non-overlapping windows and split the group in two.
    """
    start = (
        parse_date(intent.get("earliest_purchase_date"))
        or parse_date(intent.get("desired_purchase_date"))
        or today()
    )
    end = parse_date(intent.get("maximum_purchase_date")) or start
    if end < start:
        start, end = end, start
    return start, end


def _group_window(group: dict[str, Any]) -> tuple[date, date]:
    start = parse_date(group.get("purchase_window_start")) or today()
    end = parse_date(group.get("purchase_window_end")) or start
    if end < start:
        start, end = end, start
    return start, end


def compatibility(intent: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """Score one intent against one group. `compatible` False means the group is
    disqualified regardless of score."""
    reasons: list[str] = []
    blockers: list[str] = []

    if intent["category"] != group["product_category"]:
        return {"compatible": False, "score": 0, "reasons": [], "blockers": ["different category"]}
    if (intent.get("city") or "").strip().lower() != (group.get("city") or "").strip().lower():
        return {"compatible": False, "score": 0, "reasons": [], "blockers": ["different city"]}
    if group["status"] not in ("collecting_intent", "negotiating"):
        return {"compatible": False, "score": 0, "reasons": [], "blockers": [f"group is {group['status']}"]}

    category = catalog.require(intent["category"])
    spec = loads(intent.get("specifications_json"), {})
    group_spec = groups.spec_of(group)

    # --- product specification ---------------------------------------------
    matched, wildcards = 0, 0
    for field in category.grouping_fields:
        want = category.grouping_value(spec, field)
        have = category.grouping_value(group_spec, field)
        if want is None or have is None:
            wildcards += 1
            reasons.append(f"{field}: flexible")
        elif want.lower() == have.lower():
            matched += 1
            reasons.append(f"{field}: {have}")
        else:
            blockers.append(f"{field} {want} ≠ {have}")
    if blockers:
        return {"compatible": False, "score": 0, "reasons": reasons, "blockers": blockers}

    total_fields = max(1, len(category.grouping_fields))
    spec_score = SPEC_WEIGHT * (matched + 0.6 * wildcards) / total_fields

    # --- brand -------------------------------------------------------------
    want_brand = category.brand_of(spec)
    flexible = category.brand_flexible(spec)
    group_brand = group_spec.get("brand")            # set only on exact groups
    group_pref = group_spec.get("preferred_brand")

    if group["match_mode"] == "exact" and group_brand:
        if want_brand and want_brand.lower() == group_brand.lower():
            brand_score = BRAND_WEIGHT
            reasons.append(f"brand locked to {group_brand}")
        elif flexible:
            brand_score = BRAND_WEIGHT * 0.6
            reasons.append(f"open to {group_brand}")
        else:
            return {
                "compatible": False, "score": 0, "reasons": reasons,
                "blockers": [f"needs {want_brand} only, group is {group_brand} only"],
            }
    else:
        # A flexible group may end up buying any brand, so a buyer who insists
        # on one brand cannot be placed here -- they get (or start) an exact
        # group locked to that brand instead.
        if want_brand and not flexible:
            return {
                "compatible": False, "score": 0, "reasons": reasons,
                "blockers": [f"needs {want_brand} only, this group is not brand-locked"],
            }
        if not want_brand:
            brand_score = BRAND_WEIGHT * 0.8
            reasons.append("no brand preference")
        elif group_pref and group_pref.lower() == want_brand.lower():
            brand_score = BRAND_WEIGHT
            reasons.append(f"shares the group's preferred brand ({want_brand})")
        else:
            brand_score = BRAND_WEIGHT * 0.9
            reasons.append(f"prefers {want_brand}, open to alternatives")

    # --- purchase window ---------------------------------------------------
    i_start, i_end = _window(intent)
    g_start, g_end = _group_window(group)
    overlap = overlap_days(i_start, i_end, g_start, g_end)
    if overlap < settings.MATCH_MIN_WINDOW_OVERLAP_DAYS:
        return {
            "compatible": False, "score": 0, "reasons": reasons,
            "blockers": [f"purchase windows do not overlap ({overlap}d)"],
        }
    span = max(1, (max(i_end, g_end) - min(i_start, g_start)).days + 1)
    window_score = WINDOW_WEIGHT * min(1.0, overlap / span)
    reasons.append(f"purchase windows overlap {overlap} day(s)")

    # --- area --------------------------------------------------------------
    area_score = 0.0
    i_area = (intent.get("area") or "").strip().lower()
    g_area = (group.get("area") or "").strip().lower()
    if i_area and g_area and i_area == g_area:
        area_score = AREA_WEIGHT
        reasons.append(f"same area ({intent['area']})")

    # --- momentum ----------------------------------------------------------
    strong_qty = float(group.get("strong_intent_qty") or 0)
    target = group.get("next_target_qty")
    if target:
        momentum = MOMENTUM_WEIGHT * min(1.0, strong_qty / float(target))
        reasons.append(f"group already at {strong_qty:g} of {target}")
    else:
        momentum = float(MOMENTUM_WEIGHT)  # already on the best slab
        reasons.append("group is on the best price slab")

    score = BASE_SCORE + spec_score + brand_score + momentum + window_score + area_score
    return {
        "compatible": True,
        "score": round(score, 1),
        "reasons": reasons,
        "blockers": [],
        "overlap_days": overlap,
    }


def candidates(intent: dict[str, Any]) -> list[dict[str, Any]]:
    """All groups scored against this intent, best first."""
    rows = query(
        "SELECT * FROM buying_groups WHERE product_category = ? AND city = ? COLLATE NOCASE "
        "AND status IN ('collecting_intent', 'negotiating')",
        (intent["category"], intent.get("city") or ""),
    )
    scored = []
    for row in rows:
        group = dict(row)
        result = compatibility(intent, group)
        scored.append({"group": group, **result})
    scored.sort(key=lambda c: (c["compatible"], c["score"], c["group"]["strong_intent_qty"]), reverse=True)
    return scored


def best(intent: dict[str, Any]) -> dict[str, Any] | None:
    for candidate in candidates(intent):
        if candidate["compatible"] and candidate["score"] >= settings.MATCH_SCORE_THRESHOLD:
            return candidate
    return None


def assign(intent: dict[str, Any]) -> dict[str, Any]:
    """Place an intent into the best matching group, creating one if needed.

    Returns {group, created, score, reasons, alternatives}.
    """
    match = best(intent)
    if match:
        return {
            "group": match["group"],
            "created": False,
            "score": match["score"],
            "reasons": match["reasons"],
            "alternatives": [],
        }

    category = catalog.require(intent["category"])
    spec = loads(intent.get("specifications_json"), {})
    brand = category.brand_of(spec)
    flexible = category.brand_flexible(spec)
    mode = "exact" if (brand and not flexible) else "flexible"

    start, end = _window(intent)
    # A new group's window starts tight around its founder and widens as
    # members join (recalculate() recomputes it from the members).
    group = groups.create(
        category.key,
        spec,
        intent.get("city") or "",
        intent.get("area"),
        start,
        max(end, start + timedelta(days=7)),
        mode,
    )
    return {
        "group": group,
        "created": True,
        "score": 100.0,
        "reasons": ["first buyer in this group"],
        "alternatives": [],
    }


def explain(intent: dict[str, Any]) -> list[dict[str, Any]]:
    """Admin-facing: why each group did or didn't match."""
    return [
        {
            "group_code": c["group"]["code"],
            "group_id": c["group"]["id"],
            "compatible": c["compatible"],
            "score": c["score"],
            "reasons": c["reasons"],
            "blockers": c["blockers"],
            "strong_intent_qty": c["group"]["strong_intent_qty"],
        }
        for c in candidates(intent)
    ]
