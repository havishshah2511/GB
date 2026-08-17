"""Buying-group engine: creation, quantity aggregation, price recalculation.

`recalculate()` is the hub of the whole system -- every intent change funnels
through it, and it is the only place that decides a price has moved.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .. import catalog
from ..config import settings
from ..db import (
    dumps, execute, insert, loads, next_sequence, now_iso, parse_date,
    query, query_one, row_to_dict, today,
)
from ..utils import short_date
from . import pricing

ACTIVE_STRENGTHS = ("intent", "strong_intent", "ready_to_buy", "confirmed")
STRONG_STRENGTHS = ("strong_intent", "ready_to_buy", "confirmed")


# --------------------------------------------------------------------------- #
# lookup
# --------------------------------------------------------------------------- #
def get(group_id: str) -> dict[str, Any] | None:
    return row_to_dict(query_one("SELECT * FROM buying_groups WHERE id = ?", (group_id,)))


def get_by_code(code: str) -> dict[str, Any] | None:
    return row_to_dict(
        query_one("SELECT * FROM buying_groups WHERE code = ? COLLATE NOCASE", (code,))
    )


def resolve(group_ref: str) -> dict[str, Any] | None:
    return get(group_ref) or get_by_code(group_ref)


def spec_of(group: dict[str, Any]) -> dict[str, Any]:
    return loads(group.get("product_specification"), {})


def list_groups(
    category: str | None = None, city: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM buying_groups WHERE 1 = 1"
    params: list[Any] = []
    if category:
        sql += " AND product_category = ?"
        params.append(category)
    if city:
        sql += " AND city = ? COLLATE NOCASE"
        params.append(city)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY strong_intent_qty DESC, updated_at DESC"
    return [dict(r) for r in query(sql, params)]


# --------------------------------------------------------------------------- #
# creation
# --------------------------------------------------------------------------- #
def _city_code(city: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", city or "XXX").upper()
    return (letters[:3] or "XXX").ljust(3, "X")


def make_code(category_key: str, city: str) -> str:
    prefix = f"{category_key}-{_city_code(city)}"
    return f"{prefix}-{next_sequence(f'group:{prefix}', 1):03d}"


def create(
    category_key: str,
    spec: dict[str, Any],
    city: str,
    area: str | None = None,
    window_start: date | str | None = None,
    window_end: date | str | None = None,
    match_mode: str = "flexible",
) -> dict[str, Any]:
    category = catalog.require(category_key)
    resolved_spec = category.resolve_spec(spec)
    # Only the product-defining fields live on the group; per-buyer preferences
    # (budget, installation, usage...) stay on the intent.
    group_spec = {f: resolved_spec[f] for f in category.grouping_fields if resolved_spec.get(f)}
    brand = category.brand_of(resolved_spec)
    if match_mode == "exact" and brand:
        group_spec["brand"] = brand
    elif brand:
        group_spec["preferred_brand"] = brand

    code = make_code(category.key, city)
    group_id = f"GRP-{code}"
    stamp = now_iso()
    group = {
        "id": group_id,
        "code": code,
        "product_category": category.key,
        "product_specification": dumps(group_spec),
        "spec_signature": category.signature(resolved_spec),
        "match_mode": match_mode,
        "city": (city or "").strip(),
        "area": (area or "").strip() or None,
        "purchase_window_start": str(parse_date(window_start) or today()),
        "purchase_window_end": str(parse_date(window_end) or today()),
        "current_qty": 0,
        "strong_intent_qty": 0,
        "confirmed_qty": 0,
        "reference_price": None,
        "current_price": None,
        "current_slab_min_qty": None,
        "next_target_qty": None,
        "next_price": None,
        "supplier_price_confirmed": 0,
        "status": "collecting_intent",
        "created_at": stamp,
        "updated_at": stamp,
    }
    insert("buying_groups", group)
    pricing.clone_slabs_to_group(group_id, category.product_key(resolved_spec))
    recalculate(group_id, notify=False)
    return get(group_id)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# aggregation + recalculation
# --------------------------------------------------------------------------- #
def _aggregate(group_id: str) -> dict[str, Any]:
    def total(strengths: tuple[str, ...]) -> tuple[float, int]:
        marks = ", ".join("?" for _ in strengths)
        row = query_one(
            f"SELECT COALESCE(SUM(quantity), 0) AS q, COUNT(*) AS n FROM purchase_intents "
            f"WHERE group_id = ? AND status = 'active' AND intent_strength IN ({marks})",
            (group_id, *strengths),
        )
        return (float(row["q"]), int(row["n"])) if row else (0.0, 0)

    current_qty, customers = total(ACTIVE_STRENGTHS)
    strong_qty, strong_customers = total(STRONG_STRENGTHS)
    confirmed_qty, _ = total(("confirmed",))

    # The group is buyable from the earliest date any member accepts until the
    # last date they all still accept. COALESCE keeps intents written before
    # earliest_purchase_date existed working.
    window = query_one(
        "SELECT MIN(COALESCE(earliest_purchase_date, desired_purchase_date)) AS start, "
        "MAX(maximum_purchase_date) AS end "
        "FROM purchase_intents WHERE group_id = ? AND status = 'active'",
        (group_id,),
    )
    return {
        "current_qty": current_qty,
        "strong_intent_qty": strong_qty,
        "confirmed_qty": confirmed_qty,
        "customers": customers,
        "strong_customers": strong_customers,
        "window_start": window["start"] if window else None,
        "window_end": window["end"] if window else None,
    }


def recalculate(group_id: str, notify: bool = True,
                trigger_intent_id: str | None = None) -> dict[str, Any]:
    """Re-aggregate quantities, re-price, and fire notifications when the
    group's position materially changed.

    `trigger_intent_id` is the intent that caused this recalculation; its owner
    is seeing the result live in chat, so they are excluded from the outgoing
    messages.
    """
    before = get(group_id)
    if before is None:
        raise KeyError(f"Unknown group {group_id}")

    agg = _aggregate(group_id)
    slabs = pricing.group_slabs(group_id)
    calc = pricing.calculate(slabs, agg["strong_intent_qty"])

    patch = {
        "current_qty": agg["current_qty"],
        "strong_intent_qty": agg["strong_intent_qty"],
        "confirmed_qty": agg["confirmed_qty"],
        "reference_price": calc["reference_price"],
        "current_price": calc["current_price"],
        "current_slab_min_qty": calc["current_slab_min_qty"],
        "next_target_qty": calc["next_target_qty"],
        "next_price": calc["next_price"],
        "updated_at": now_iso(),
    }
    if agg["window_start"]:
        patch["purchase_window_start"] = agg["window_start"]
    if agg["window_end"]:
        patch["purchase_window_end"] = agg["window_end"]

    sets = ", ".join(f"{k} = ?" for k in patch)
    execute(f"UPDATE buying_groups SET {sets} WHERE id = ?", [*patch.values(), group_id])

    after = get(group_id)
    assert after is not None
    price_dropped = (
        before["current_price"] is not None
        and after["current_price"] is not None
        and after["current_price"] < before["current_price"]
    )
    result = {
        "group": after,
        "before": before,
        "price_changed": before["current_price"] != after["current_price"],
        "price_dropped": price_dropped,
        "quantity_changed": before["strong_intent_qty"] != after["strong_intent_qty"],
        "customers": agg["customers"],
        "strong_customers": agg["strong_customers"],
        "notifications": [],
    }

    if notify and (result["price_changed"] or result["quantity_changed"]):
        from . import notifications  # local import avoids a cycle

        result["notifications"] = notifications.on_group_changed(
            after, before, price_dropped, exclude_intent_id=trigger_intent_id
        )
    return result


def recalculate_all(notify: bool = True) -> list[dict[str, Any]]:
    return [
        recalculate(row["id"], notify=notify)
        for row in query("SELECT id FROM buying_groups WHERE status != 'closed'")
    ]


# --------------------------------------------------------------------------- #
# membership
# --------------------------------------------------------------------------- #
def members(group_id: str, active_only: bool = True) -> list[dict[str, Any]]:
    sql = (
        "SELECT i.*, c.name AS customer_name, c.mobile AS customer_mobile "
        "FROM purchase_intents i LEFT JOIN customers c ON c.id = i.customer_id "
        "WHERE i.group_id = ?"
    )
    params: list[Any] = [group_id]
    if active_only:
        sql += " AND i.status = 'active'"
    sql += " ORDER BY i.created_at DESC"
    return [dict(r) for r in query(sql, params)]


def notifiable_members(group_id: str) -> list[dict[str, Any]]:
    """Active, contactable buyers -- the audience for group notifications."""
    return [
        m
        for m in members(group_id)
        if m.get("customer_mobile") and m["intent_strength"] in STRONG_STRENGTHS
    ]


# --------------------------------------------------------------------------- #
# admin operations
# --------------------------------------------------------------------------- #
def move_intent(intent_id: str, target_group_id: str) -> dict[str, Any]:
    row = query_one("SELECT group_id FROM purchase_intents WHERE id = ?", (intent_id,))
    if row is None:
        raise KeyError(f"Unknown intent {intent_id}")
    source = row["group_id"]
    execute(
        "UPDATE purchase_intents SET group_id = ?, updated_at = ? WHERE id = ?",
        (target_group_id, now_iso(), intent_id),
    )
    out = {"target": recalculate(target_group_id)}
    if source and source != target_group_id:
        out["source"] = recalculate(source)
    return out


def merge(source_id: str, target_id: str) -> dict[str, Any]:
    if source_id == target_id:
        raise ValueError("Cannot merge a group into itself")
    source, target = get(source_id), get(target_id)
    if not source or not target:
        raise KeyError("Both groups must exist")
    if source["product_category"] != target["product_category"]:
        raise ValueError("Groups belong to different product categories")

    execute(
        "UPDATE purchase_intents SET group_id = ?, updated_at = ? WHERE group_id = ?",
        (target_id, now_iso(), source_id),
    )
    execute(
        "UPDATE referrals SET group_id = ? WHERE group_id = ?", (target_id, source_id)
    )
    execute(
        "UPDATE buying_groups SET status = 'merged', updated_at = ? WHERE id = ?",
        (now_iso(), source_id),
    )
    recalculate(source_id, notify=False)
    return recalculate(target_id)


def split(group_id: str, intent_ids: list[str], match_mode: str | None = None) -> dict[str, Any]:
    """Pull a set of intents out of a group into a brand new one."""
    source = get(group_id)
    if source is None:
        raise KeyError(f"Unknown group {group_id}")
    if not intent_ids:
        raise ValueError("No intents selected")

    marks = ", ".join("?" for _ in intent_ids)
    rows = query(
        f"SELECT * FROM purchase_intents WHERE id IN ({marks}) AND group_id = ?",
        (*intent_ids, group_id),
    )
    if not rows:
        raise ValueError("None of those intents belong to this group")

    first = dict(rows[0])
    spec = loads(first["specifications_json"], {})
    new_group = create(
        first["category"],
        spec,
        first["city"] or source["city"],
        first["area"],
        first["desired_purchase_date"],
        first["maximum_purchase_date"],
        match_mode or source["match_mode"],
    )
    execute(
        f"UPDATE purchase_intents SET group_id = ?, updated_at = ? WHERE id IN ({marks})",
        (new_group["id"], now_iso(), *intent_ids),
    )
    return {"new_group": recalculate(new_group["id"], notify=False), "source": recalculate(group_id, notify=False)}


def set_status(group_id: str, status: str) -> None:
    execute(
        "UPDATE buying_groups SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), group_id),
    )


# --------------------------------------------------------------------------- #
# serialisation
# --------------------------------------------------------------------------- #
def to_api(group: dict[str, Any], customer_qty: float = 0) -> dict[str, Any]:
    """The shape described in spec section 28, plus render-ready extras."""
    category = catalog.require(group["product_category"])
    spec = spec_of(group)
    facts = pricing.price_facts(group, customer_qty)
    gap = facts.get("gap_to_next_price")
    return {
        "group_id": group["code"],
        "id": group["id"],
        "code": group["code"],
        "label": pricing.group_label(group),
        "product": {
            "category": category.key,
            "category_label": category.label,
            "emoji": category.emoji,
            **spec,
            "description": category.spec_description(spec),
        },
        "location": {"city": group["city"], "area": group["area"]},
        "match_mode": group["match_mode"],
        "quantity": {
            "total_intent_qty": group["current_qty"],
            "strong_intent_qty": group["strong_intent_qty"],
            "confirmed_qty": group["confirmed_qty"],
            "unit": category.unit,
        },
        "pricing": {
            "reference_price": group["reference_price"],
            "current_price": group["current_price"],
            "current_slab_min_qty": group["current_slab_min_qty"],
            "next_slab_qty": group["next_target_qty"],
            "next_price": group["next_price"],
            "price_status": "supplier_confirmed" if group["supplier_price_confirmed"] else "indicative",
        },
        "purchase_window": {
            "start": group["purchase_window_start"],
            "end": group["purchase_window_end"],
            "label": f"{short_date(group['purchase_window_start'])} – {short_date(group['purchase_window_end'])}",
        },
        "gap_to_next_price": gap,
        "status": group["status"],
        "facts": facts,
        "slabs": pricing.slab_table(group),
    }


def summary_for_admin(group: dict[str, Any]) -> dict[str, Any]:
    agg = _aggregate(group["id"])
    referral_qty = query_one(
        "SELECT COALESCE(SUM(quantity_generated), 0) AS q FROM referrals WHERE group_id = ?",
        (group["id"],),
    )
    data = to_api(group)
    data["customers"] = agg["customers"]
    data["strong_customers"] = agg["strong_customers"]
    data["referral_quantity"] = float(referral_qty["q"]) if referral_qty else 0.0
    return data


def default_window(days: int = 14) -> tuple[str, str]:
    start = today()
    return str(start), str(start + timedelta(days=days))


def stats() -> dict[str, Any]:
    row = query_one(
        "SELECT COUNT(*) AS groups, COALESCE(SUM(current_qty), 0) AS qty, "
        "COALESCE(SUM(strong_intent_qty), 0) AS strong FROM buying_groups "
        "WHERE status = 'collecting_intent'"
    )
    return {
        "active_groups": int(row["groups"]) if row else 0,
        "total_qty": float(row["qty"]) if row else 0.0,
        "strong_qty": float(row["strong"]) if row else 0.0,
        "min_overlap_days": settings.MATCH_MIN_WINDOW_OVERLAP_DAYS,
    }
