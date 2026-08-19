"""Purchase intents: creation, strength grading, expiry and reconfirmation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .. import catalog
from ..config import settings
from ..db import (
    dumps, execute, insert, loads, new_id, now_iso, parse_date, query,
    query_one, row_to_dict, today,
)
from ..utils import to_float
from . import customers, groups, matching

STRENGTH_ORDER = ("enquiry", "intent", "strong_intent", "ready_to_buy", "confirmed")
STRENGTH_LABELS = {
    "enquiry": "Enquiry",
    "intent": "Intent",
    "strong_intent": "Strong Intent",
    "ready_to_buy": "Ready to Buy",
    "confirmed": "Confirmed",
}


# --------------------------------------------------------------------------- #
# grading
# --------------------------------------------------------------------------- #
def grade(state: dict[str, Any], explicit: str | None = None) -> str:
    """Spec section 24. `explicit` lets the chat/admin push an intent up to
    ready_to_buy or confirmed."""
    if explicit in ("ready_to_buy", "confirmed"):
        return explicit

    has_product = bool(state.get("category"))
    has_qty = (to_float(state.get("quantity"), 0) or 0) > 0
    has_location = bool(state.get("city"))
    has_date = bool(state.get("desired_purchase_date"))
    has_mobile = bool(state.get("mobile"))

    if has_product and has_qty and has_location and has_date and has_mobile:
        return "strong_intent"
    if has_product and has_qty:
        return "intent"
    return "enquiry"


def expiry_for(desired: date | None, maximum: date | None) -> date:
    anchor = maximum or desired or today()
    return anchor + timedelta(days=settings.INTENT_GRACE_DAYS)


def earliest_for(state: dict[str, Any], desired: date | None) -> date | None:
    """The first date this buyer would accept.

    "Within 15 days" is a deadline -- they are available from today, and pooling
    them with a "within 7 days" buyer is exactly the point of the product. Only
    an explicitly chosen calendar date means "not before then".
    """
    if state.get("purchase_within_days") is not None:
        return today()
    explicit = parse_date(state.get("earliest_purchase_date"))
    return explicit or desired


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #
def get(intent_id: str) -> dict[str, Any] | None:
    return row_to_dict(query_one("SELECT * FROM purchase_intents WHERE id = ?", (intent_id,)))


def get_full(intent_id: str) -> dict[str, Any] | None:
    row = query_one(
        "SELECT i.*, c.name AS customer_name, c.mobile AS customer_mobile, "
        "c.area AS customer_area, c.city AS customer_city, g.code AS group_code "
        "FROM purchase_intents i "
        "LEFT JOIN customers c ON c.id = i.customer_id "
        "LEFT JOIN buying_groups g ON g.id = i.group_id "
        "WHERE i.id = ?",
        (intent_id,),
    )
    return row_to_dict(row)


def list_intents(
    status: str | None = None,
    strength: str | None = None,
    category: str | None = None,
    city: str | None = None,
    group_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT i.*, c.name AS customer_name, c.mobile AS customer_mobile, g.code AS group_code "
        "FROM purchase_intents i "
        "LEFT JOIN customers c ON c.id = i.customer_id "
        "LEFT JOIN buying_groups g ON g.id = i.group_id WHERE 1 = 1"
    )
    params: list[Any] = []
    for column, value in (
        ("i.status", status), ("i.intent_strength", strength),
        ("i.category", category), ("i.group_id", group_id),
    ):
        if value:
            sql += f" AND {column} = ?"
            params.append(value)
    if city:
        sql += " AND i.city = ? COLLATE NOCASE"
        params.append(city)
    sql += " ORDER BY i.created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in query(sql, params)]


def list_by_customer(customer_id: str, active_only: bool = False) -> list[dict[str, Any]]:
    """Every request a returning customer has placed, newest first."""
    sql = (
        "SELECT i.*, g.code AS group_code, g.city AS group_city, "
        "g.strong_intent_qty AS group_qty, g.current_price AS group_price, "
        "g.next_target_qty AS group_next_target, g.next_price AS group_next_price, "
        "g.reference_price AS group_reference_price, "
        "g.supplier_price_confirmed AS group_price_confirmed "
        "FROM purchase_intents i "
        "LEFT JOIN buying_groups g ON g.id = i.group_id "
        "WHERE i.customer_id = ?"
    )
    params: list[Any] = [customer_id]
    if active_only:
        sql += " AND i.status = 'active'"
    sql += " ORDER BY i.created_at DESC"
    return [dict(r) for r in query(sql, params)]


def summarise_for_customer(intent: dict[str, Any]) -> str:
    """One-line description used in chat and on the status page."""
    category = catalog.get(intent["category"])
    qty = float(intent.get("quantity") or 0)
    qty_text = category.qty_label(qty, intent.get("unit")) if category else f"{qty:g}"
    where = intent.get("city") or ""
    product = intent.get("product") or (category.label if category else intent["category"])
    return f"{qty_text} · {product}" + (f" · {where}" if where else "")


# --------------------------------------------------------------------------- #
# write
# --------------------------------------------------------------------------- #
def create(state: dict[str, Any], conversation_id: str | None = None,
           referral_code: str | None = None) -> dict[str, Any]:
    """Turn a collected slot bag into a stored purchase intent.

    `state` uses slot names: category, quantity, city, area, name, mobile,
    desired_purchase_date, maximum_purchase_date, can_wait, plus category slots.
    """
    category = catalog.require(state.get("category"))
    customer = customers.upsert(
        name=state.get("name"),
        mobile=state.get("mobile"),
        area=state.get("area"),
        city=state.get("city"),
        pincode=state.get("pincode"),
    )

    spec = {
        name: state[name]
        for name in (s.name for s in category.slots)
        if state.get(name) not in (None, "", [])
    }
    if category.open_ended and (state.get("unit") or "").strip():
        spec["unit"] = state["unit"].strip()
    desired = parse_date(state.get("desired_purchase_date"))
    maximum = parse_date(state.get("maximum_purchase_date")) or desired
    quantity = to_float(state.get("quantity"), 0) or 0.0
    earliest = earliest_for(state, desired)

    stamp = now_iso()
    intent_id = new_id("INT", width=5, start=10000)
    record = {
        "id": intent_id,
        "customer_id": customer["id"],
        "conversation_id": conversation_id,
        "category": category.key,
        "product": category.spec_description(spec),
        "specifications_json": dumps(spec),
        "quantity": quantity,
        "unit": (state.get("unit") or "").strip() or category.unit,
        "area": state.get("area"),
        "city": state.get("city"),
        "earliest_purchase_date": str(earliest) if earliest else None,
        "desired_purchase_date": str(desired) if desired else None,
        "maximum_purchase_date": str(maximum) if maximum else None,
        "can_wait": 1 if state.get("can_wait") else 0,
        "brand_flexible": 1 if category.brand_flexible(spec) else 0,
        "budget": to_float(state.get("budget")),
        "status": "active",
        "intent_strength": grade({**state, "category": category.key}),
        "group_id": None,
        "referral_id": None,
        "created_at": stamp,
        "updated_at": stamp,
        "expires_at": str(expiry_for(desired, maximum)),
        "reconfirm_sent_at": None,
    }
    insert("purchase_intents", record)

    result = match_and_join(intent_id)

    if referral_code:
        from . import referrals

        referrals.attribute_intent(referral_code, get_full(intent_id) or {})

    return {
        "intent": get_full(intent_id),
        "customer": customer,
        **result,
    }


def match_and_join(intent_id: str) -> dict[str, Any]:
    """Run the matching engine and attach the intent to a group."""
    intent = get(intent_id)
    if intent is None:
        raise KeyError(f"Unknown intent {intent_id}")

    assignment = matching.assign(intent)
    group = assignment["group"]
    execute(
        "UPDATE purchase_intents SET group_id = ?, updated_at = ? WHERE id = ?",
        (group["id"], now_iso(), intent_id),
    )
    outcome = groups.recalculate(group["id"], trigger_intent_id=intent_id)
    return {
        "group": outcome["group"],
        "group_created": assignment["created"],
        "match_score": assignment["score"],
        "match_reasons": assignment["reasons"],
        "recalculation": outcome,
    }


def update(intent_id: str, patch: dict[str, Any], rematch: bool = False) -> dict[str, Any]:
    """Partial update. Recomputes derived fields and re-runs pricing."""
    intent = get(intent_id)
    if intent is None:
        raise KeyError(f"Unknown intent {intent_id}")
    category = catalog.require(intent["category"])

    columns = {
        "quantity", "area", "city", "earliest_purchase_date", "desired_purchase_date",
        "maximum_purchase_date", "can_wait", "brand_flexible", "budget", "status",
        "intent_strength", "group_id",
    }
    data: dict[str, Any] = {k: v for k, v in patch.items() if k in columns}

    if "specifications" in patch or "specifications_json" in patch:
        spec = patch.get("specifications") or loads(patch.get("specifications_json"), {})
        merged = {**loads(intent["specifications_json"], {}), **spec}
        data["specifications_json"] = dumps(merged)
        data["product"] = category.spec_description(merged)
        data["brand_flexible"] = 1 if category.brand_flexible(merged) else 0

    if "quantity" in data:
        data["quantity"] = to_float(data["quantity"], 0) or 0.0
    for key in ("can_wait", "brand_flexible"):
        if key in data:
            data[key] = 1 if data[key] in (1, True, "1", "true", "yes", "Yes") else 0

    desired = parse_date(data.get("desired_purchase_date", intent["desired_purchase_date"]))
    maximum = parse_date(data.get("maximum_purchase_date", intent["maximum_purchase_date"]))
    if "desired_purchase_date" in data or "maximum_purchase_date" in data:
        data["expires_at"] = str(expiry_for(desired, maximum))
        if data.get("status") is None and intent["status"] == "expired":
            data["status"] = "active"

    data["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in data)
    execute(f"UPDATE purchase_intents SET {sets} WHERE id = ?", [*data.values(), intent_id])

    updated = get(intent_id)
    assert updated is not None
    result: dict[str, Any] = {"intent": get_full(intent_id)}

    if rematch:
        old_group = intent["group_id"]
        result.update(match_and_join(intent_id))
        if old_group and old_group != updated["group_id"]:
            groups.recalculate(old_group)
    elif updated["group_id"]:
        result["recalculation"] = groups.recalculate(updated["group_id"])
        result["group"] = result["recalculation"]["group"]
    return result


def set_strength(intent_id: str, strength: str) -> dict[str, Any]:
    if strength not in STRENGTH_ORDER:
        raise ValueError(f"Unknown intent strength {strength!r}")
    return update(intent_id, {"intent_strength": strength})


def set_status(intent_id: str, status: str) -> dict[str, Any]:
    if status not in ("active", "expired", "cancelled", "fulfilled"):
        raise ValueError(f"Unknown intent status {status!r}")
    return update(intent_id, {"status": status})


def reconfirm(intent_id: str, new_date: str | None = None, still_interested: bool = True) -> dict[str, Any]:
    """Handles the answers to the pre-expiry nudge (spec section 25)."""
    if not still_interested:
        return set_status(intent_id, "cancelled")
    patch: dict[str, Any] = {"status": "active"}
    if new_date:
        parsed = parse_date(new_date)
        if parsed:
            patch["desired_purchase_date"] = str(parsed)
            patch["maximum_purchase_date"] = str(parsed + timedelta(days=7))
    else:
        extended = today() + timedelta(days=14)
        patch["maximum_purchase_date"] = str(extended)
    execute(
        "UPDATE purchase_intents SET reconfirm_sent_at = NULL WHERE id = ?", (intent_id,)
    )
    return update(intent_id, patch)


# --------------------------------------------------------------------------- #
# lifecycle sweeps (run by the background worker)
# --------------------------------------------------------------------------- #
def expire_due() -> dict[str, Any]:
    """Mark past-deadline intents expired and drop their quantity from groups."""
    rows = query(
        "SELECT id, group_id FROM purchase_intents "
        "WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < ?",
        (str(today()),),
    )
    affected_groups = set()
    for row in rows:
        execute(
            "UPDATE purchase_intents SET status = 'expired', updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        if row["group_id"]:
            affected_groups.add(row["group_id"])
    for group_id in affected_groups:
        groups.recalculate(group_id)
    return {"expired": len(rows), "groups_recalculated": len(affected_groups)}


def reconfirmation_due() -> list[dict[str, Any]]:
    """Active intents approaching their deadline that have not been nudged."""
    horizon = today() + timedelta(days=settings.RECONFIRM_LEAD_DAYS)
    rows = query(
        "SELECT i.*, c.name AS customer_name, c.mobile AS customer_mobile, g.code AS group_code "
        "FROM purchase_intents i "
        "LEFT JOIN customers c ON c.id = i.customer_id "
        "LEFT JOIN buying_groups g ON g.id = i.group_id "
        "WHERE i.status = 'active' AND i.reconfirm_sent_at IS NULL "
        "AND i.expires_at IS NOT NULL AND i.expires_at <= ?",
        (str(horizon),),
    )
    return [dict(r) for r in rows]


def mark_reconfirm_sent(intent_id: str) -> None:
    execute(
        "UPDATE purchase_intents SET reconfirm_sent_at = ? WHERE id = ?",
        (now_iso(), intent_id),
    )


# --------------------------------------------------------------------------- #
# serialisation
# --------------------------------------------------------------------------- #
def to_api(intent: dict[str, Any]) -> dict[str, Any]:
    """Spec section 9 shape."""
    category = catalog.get(intent["category"])
    spec = loads(intent.get("specifications_json"), {})
    return {
        "intent_id": intent["id"],
        "customer": {
            "name": intent.get("customer_name"),
            "mobile": intent.get("customer_mobile"),
            "area": intent.get("area"),
            "city": intent.get("city"),
        },
        "requirement": {
            "product": intent["category"],
            "description": intent.get("product"),
            "quantity": intent["quantity"],
            "unit": intent.get("unit"),
            **spec,
            "alternative_brand_allowed": bool(intent["brand_flexible"]),
        },
        "purchase_timing": {
            "desired_date": intent["desired_purchase_date"],
            "can_wait": bool(intent["can_wait"]),
            "maximum_wait_date": intent["maximum_purchase_date"],
        },
        "group_id": intent.get("group_code") or intent.get("group_id"),
        "status": intent["intent_strength"],
        "record_status": intent["status"],
        "expires_at": intent["expires_at"],
        "created_at": intent["created_at"],
        "unit_label": category.unit if category else "",
    }


def stats() -> dict[str, Any]:
    row = query_one(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active, "
        "COALESCE(SUM(CASE WHEN status = 'active' AND intent_strength IN "
        "  ('strong_intent','ready_to_buy','confirmed') THEN 1 ELSE 0 END), 0) AS strong, "
        "COALESCE(SUM(CASE WHEN status = 'active' AND intent_strength IN "
        "  ('intent','strong_intent','ready_to_buy','confirmed') THEN quantity ELSE 0 END), 0) AS demand_qty, "
        "COALESCE(SUM(CASE WHEN status = 'active' AND intent_strength IN "
        "  ('strong_intent','ready_to_buy','confirmed') THEN quantity ELSE 0 END), 0) AS strong_qty "
        "FROM purchase_intents"
    )
    data = dict(row) if row else {}
    expiring = query_one(
        "SELECT COUNT(*) AS n FROM purchase_intents WHERE status = 'active' "
        "AND expires_at IS NOT NULL AND expires_at <= ?",
        (str(today() + timedelta(days=settings.RECONFIRM_LEAD_DAYS)),),
    )
    data["expiring_soon"] = int(expiring["n"]) if expiring else 0
    return data
