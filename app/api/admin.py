"""Admin API. Spec section 30 -- every operation the operator needs.

Auth is a single operator account, accepted either as a signed session cookie
(set by the dashboard's login form) or HTTP Basic (for curl and monitoring).
Deliberately minimal for an MVP with one back-office user; replace
`require_admin` when you add staff accounts and roles.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .. import catalog
from ..config import settings
from ..db import insert, loads, new_id, now_iso, query, query_one, today
from ..models import (
    BroadcastIn, MergeIn, MoveIntentIn, SlabsIn, SplitIn, SupplierConfirmIn,
)
from ..services import (
    conversation, customers, groups, intents, matching, notifications, pricing, referrals,
)

security = HTTPBasic(auto_error=False)
SESSION_COOKIE = "gb_admin"


# --------------------------------------------------------------------------- #
# authentication
# --------------------------------------------------------------------------- #
def check_password(username: str, password: str) -> bool:
    return (
        secrets.compare_digest(username, settings.ADMIN_USER)
        and secrets.compare_digest(password, settings.ADMIN_PASSWORD)
    )


def _sign(payload: str) -> str:
    return hmac.new(
        settings.admin_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue_session() -> str:
    """`user|expiry|signature` — stateless, so there is no session table."""
    expires = int(time.time()) + settings.ADMIN_SESSION_HOURS * 3600
    payload = f"{settings.ADMIN_USER}|{expires}"
    return f"{payload}|{_sign(payload)}"


def valid_session(cookie: str | None) -> bool:
    if not cookie:
        return False
    parts = cookie.split("|")
    if len(parts) != 3:
        return False
    user, expires, signature = parts
    payload = f"{user}|{expires}"
    if not hmac.compare_digest(signature, _sign(payload)):
        return False
    try:
        return int(expires) > time.time() and secrets.compare_digest(user, settings.ADMIN_USER)
    except ValueError:
        return False


def is_authenticated(request: Request) -> bool:
    return valid_session(request.cookies.get(SESSION_COOKIE))


def require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    """Accepts either the dashboard's session cookie or HTTP Basic (for curl,
    scripts and monitoring)."""
    if is_authenticated(request):
        return settings.ADMIN_USER
    if credentials is not None and check_password(credentials.username, credentials.password):
        return credentials.username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin authentication required",
        headers={"WWW-Authenticate": 'Basic realm="Group Buying Admin"'},
    )


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _audit(action: str, entity: str, entity_id: str, detail: dict[str, Any] | None = None) -> None:
    from ..db import dumps

    insert(
        "admin_audit",
        {
            "id": new_id("AUD", width=6, start=1),
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "detail": dumps(detail or {}),
            "created_at": now_iso(),
        },
    )


# --------------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------------- #
@router.get("/overview")
def overview() -> dict[str, Any]:
    intent_stats = intents.stats()
    group_stats = groups.stats()

    by_product = [
        dict(r)
        for r in query(
            "SELECT category, COUNT(*) AS intents, COALESCE(SUM(quantity), 0) AS qty, "
            "COALESCE(SUM(CASE WHEN intent_strength IN ('strong_intent','ready_to_buy','confirmed') "
            "  THEN quantity ELSE 0 END), 0) AS strong_qty "
            "FROM purchase_intents WHERE status = 'active' GROUP BY category ORDER BY qty DESC"
        )
    ]
    by_city = [
        dict(r)
        for r in query(
            "SELECT city, COUNT(*) AS intents, COALESCE(SUM(quantity), 0) AS qty "
            "FROM purchase_intents WHERE status = 'active' AND city IS NOT NULL "
            "GROUP BY city ORDER BY qty DESC LIMIT 12"
        )
    ]
    by_area = [
        dict(r)
        for r in query(
            "SELECT city, area, COUNT(*) AS intents, COALESCE(SUM(quantity), 0) AS qty "
            "FROM purchase_intents WHERE status = 'active' AND area IS NOT NULL "
            "GROUP BY city, area ORDER BY qty DESC LIMIT 12"
        )
    ]
    by_window = [
        dict(r)
        for r in query(
            "SELECT desired_purchase_date AS date, COUNT(*) AS intents, "
            "COALESCE(SUM(quantity), 0) AS qty FROM purchase_intents "
            "WHERE status = 'active' AND desired_purchase_date IS NOT NULL "
            "GROUP BY desired_purchase_date ORDER BY desired_purchase_date LIMIT 30"
        )
    ]
    by_strength = [
        dict(r)
        for r in query(
            "SELECT intent_strength, COUNT(*) AS intents, COALESCE(SUM(quantity), 0) AS qty "
            "FROM purchase_intents WHERE status = 'active' GROUP BY intent_strength"
        )
    ]

    return {
        "intents": intent_stats,
        "groups": group_stats,
        "referrals": referrals.stats(),
        "notifications": notifications.stats(),
        "customers": int(query_one("SELECT COUNT(*) AS n FROM customers")["n"]),
        "demand_by_product": by_product,
        "demand_by_city": by_city,
        "demand_by_area": by_area,
        "demand_by_date": by_window,
        "by_strength": by_strength,
        "expiring": expiring_intents()["intents"],
        "engine": {"llm_enabled": settings.llm_enabled, "model": settings.ANTHROPIC_MODEL},
    }


@router.get("/demand-by-product")
def demand_by_product() -> dict[str, Any]:
    """Product-wise demand and, for each product, how much more quantity is
    needed to close the next price level."""
    products: dict[str, dict[str, Any]] = {}

    for category in catalog.all_categories():
        products[category.key] = {
            "category": category.key,
            "label": category.label,
            "emoji": category.emoji,
            "unit": category.unit,
            "groups": 0,
            "customers": 0,
            "total_qty": 0.0,
            "strong_qty": 0.0,
            "confirmed_qty": 0.0,
            "pending_qty": 0.0,      # units still needed to unlock a better price
            "at_top_slab": 0,        # groups with no cheaper level left
            "group_rows": [],
        }

    for group in groups.list_groups():
        summary = groups.summary_for_admin(group)
        bucket = products.get(group["product_category"])
        if bucket is None:
            continue
        gap = summary.get("gap_to_next_price")
        bucket["groups"] += 1
        bucket["customers"] += int(summary.get("customers") or 0)
        bucket["total_qty"] += float(summary["quantity"]["total_intent_qty"] or 0)
        bucket["strong_qty"] += float(summary["quantity"]["strong_intent_qty"] or 0)
        bucket["confirmed_qty"] += float(summary["quantity"]["confirmed_qty"] or 0)
        if gap is None:
            bucket["at_top_slab"] += 1
        else:
            bucket["pending_qty"] += float(gap)
        bucket["group_rows"].append(
            {
                "code": group["code"],
                "label": summary["label"],
                "city": group["city"],
                "customers": summary.get("customers"),
                "strong_qty": summary["quantity"]["strong_intent_qty"],
                "current_price": summary["pricing"]["current_price"],
                "next_target_qty": summary["pricing"]["next_slab_qty"],
                "next_price": summary["pricing"]["next_price"],
                "pending_qty": gap,
                "price_status": summary["pricing"]["price_status"],
                "window": summary["purchase_window"]["label"],
            }
        )

    for bucket in products.values():
        bucket["group_rows"].sort(
            key=lambda r: (r["pending_qty"] is None, r["pending_qty"] or 0)
        )

    ordered = sorted(products.values(), key=lambda p: (-p["total_qty"], p["label"]))
    return {"products": ordered}


@router.get("/expiring")
def expiring_intents(days: int | None = None) -> dict[str, Any]:
    horizon = today() + timedelta(days=days if days is not None else settings.RECONFIRM_LEAD_DAYS)
    rows = query(
        "SELECT i.*, c.name AS customer_name, c.mobile AS customer_mobile, g.code AS group_code "
        "FROM purchase_intents i "
        "LEFT JOIN customers c ON c.id = i.customer_id "
        "LEFT JOIN buying_groups g ON g.id = i.group_id "
        "WHERE i.status = 'active' AND i.expires_at IS NOT NULL AND i.expires_at <= ? "
        "ORDER BY i.expires_at LIMIT 50",
        (str(horizon),),
    )
    return {"intents": [dict(r) for r in rows]}


# --------------------------------------------------------------------------- #
# groups
# --------------------------------------------------------------------------- #
@router.get("/groups")
def list_groups(category: str | None = None, city: str | None = None,
                status_filter: str | None = None) -> dict[str, Any]:
    return {
        "groups": [
            groups.summary_for_admin(g)
            for g in groups.list_groups(category, city, status_filter)
        ]
    }


@router.get("/groups/{group_ref}")
def group_detail(group_ref: str) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, "Unknown group")
    members = groups.members(group["id"], active_only=False)
    return {
        **groups.summary_for_admin(group),
        "members": [
            {
                **m,
                "specifications": loads(m.get("specifications_json"), {}),
                "strength_label": intents.STRENGTH_LABELS.get(m["intent_strength"], m["intent_strength"]),
            }
            for m in members
        ],
        "notifications": notifications.history(group_id=group["id"], limit=25),
        "referrals": [
            dict(r)
            for r in query(
                "SELECT r.*, c.name AS referrer_name FROM referrals r "
                "LEFT JOIN customers c ON c.id = r.referrer_customer_id "
                "WHERE r.group_id = ? ORDER BY r.quantity_generated DESC",
                (group["id"],),
            )
        ],
    }


@router.put("/groups/{group_ref}/slabs")
def update_slabs(group_ref: str, payload: SlabsIn) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, "Unknown group")
    if not payload.slabs:
        raise HTTPException(400, "At least one slab is required")
    category = catalog.require(group["product_category"])
    pricing.replace_group_slabs(
        group["id"],
        [s.model_dump() for s in payload.slabs],
        category.product_key(groups.spec_of(group)),
    )
    _audit("update_slabs", "group", group["id"], {"slabs": len(payload.slabs)})
    outcome = groups.recalculate(group["id"])
    return {"group": groups.to_api(outcome["group"]), "slabs": pricing.slab_table(outcome["group"])}


@router.post("/groups/{group_ref}/supplier-price")
def supplier_price(group_ref: str, payload: SupplierConfirmIn) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, "Unknown group")
    pricing.set_supplier_confirmed(group["id"], payload.confirmed, payload.supplier_id)
    _audit("supplier_price", "group", group["id"], payload.model_dump())
    return {"group": groups.to_api(groups.get(group["id"]))}  # type: ignore[arg-type]


@router.post("/groups/{group_ref}/status")
def set_group_status(group_ref: str, new_status: str) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, "Unknown group")
    if new_status not in ("collecting_intent", "negotiating", "closed", "merged"):
        raise HTTPException(400, f"Unknown status {new_status}")
    groups.set_status(group["id"], new_status)
    _audit("group_status", "group", group["id"], {"status": new_status})
    return {"group": groups.to_api(groups.get(group["id"]))}  # type: ignore[arg-type]


@router.post("/groups/merge")
def merge_groups(payload: MergeIn) -> dict[str, Any]:
    source = groups.resolve(payload.source_group_id)
    target = groups.resolve(payload.target_group_id)
    if source is None or target is None:
        raise HTTPException(404, "Both groups must exist")
    try:
        outcome = groups.merge(source["id"], target["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _audit("merge", "group", target["id"], {"source": source["code"]})
    return {"group": groups.to_api(outcome["group"])}


@router.post("/groups/{group_ref}/split")
def split_group(group_ref: str, payload: SplitIn) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, "Unknown group")
    try:
        outcome = groups.split(group["id"], payload.intent_ids, payload.match_mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _audit("split", "group", group["id"], {"intents": payload.intent_ids})
    return {
        "new_group": groups.to_api(outcome["new_group"]["group"]),
        "source_group": groups.to_api(outcome["source"]["group"]),
    }


@router.post("/groups/{group_ref}/notify")
def broadcast(group_ref: str, payload: BroadcastIn) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, "Unknown group")
    sent = notifications.broadcast(group["id"], payload.message, payload.channel)
    _audit("broadcast", "group", group["id"], {"recipients": sent})
    return {"queued": sent}


# --------------------------------------------------------------------------- #
# intents
# --------------------------------------------------------------------------- #
@router.get("/intents")
def list_intents(status_filter: str | None = None, strength: str | None = None,
                 category: str | None = None, city: str | None = None,
                 group_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    rows = intents.list_intents(status_filter, strength, category, city, group_id, limit)
    return {
        "intents": [
            {**r, "specifications": loads(r.get("specifications_json"), {})}
            for r in rows
        ]
    }


@router.get("/intents/{intent_id}")
def intent_detail(intent_id: str) -> dict[str, Any]:
    intent = intents.get_full(intent_id)
    if intent is None:
        raise HTTPException(404, "Unknown intent")
    record = None
    if intent.get("conversation_id"):
        record = query_one("SELECT * FROM conversations WHERE id = ?", (intent["conversation_id"],))
    raw = intents.get(intent_id) or {}
    return {
        "intent": {**intent, "specifications": loads(intent.get("specifications_json"), {})},
        "api_shape": intents.to_api(intent),
        "conversation": {
            "id": record["id"],
            "session_id": record["session_id"],
            "messages": loads(record["messages"], []),
            "extracted_information": loads(record["extracted_information"], {}),
        } if record else None,
        "match_candidates": matching.explain(raw),
        "notifications": notifications.history(customer_id=intent.get("customer_id"), limit=25),
    }


@router.put("/intents/{intent_id}")
def correct_intent(intent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    if intents.get(intent_id) is None:
        raise HTTPException(404, "Unknown intent")
    rematch = bool(patch.pop("rematch", False))
    result = intents.update(intent_id, patch, rematch=rematch)
    _audit("correct_intent", "intent", intent_id, patch)
    return {"intent": result["intent"]}


@router.post("/intents/move")
def move_intent(payload: MoveIntentIn) -> dict[str, Any]:
    target = groups.resolve(payload.target_group_id)
    if target is None:
        raise HTTPException(404, "Unknown target group")
    if intents.get(payload.intent_id) is None:
        raise HTTPException(404, "Unknown intent")
    outcome = groups.move_intent(payload.intent_id, target["id"])
    _audit("move_intent", "intent", payload.intent_id, {"target": target["code"]})
    return {"target_group": groups.to_api(outcome["target"]["group"])}


@router.post("/intents/{intent_id}/status")
def change_intent_status(intent_id: str, new_status: str) -> dict[str, Any]:
    if intents.get(intent_id) is None:
        raise HTTPException(404, "Unknown intent")
    try:
        result = intents.set_status(intent_id, new_status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _audit("intent_status", "intent", intent_id, {"status": new_status})
    return {"intent": result["intent"]}


@router.post("/intents/{intent_id}/strength")
def change_intent_strength(intent_id: str, strength: str) -> dict[str, Any]:
    if intents.get(intent_id) is None:
        raise HTTPException(404, "Unknown intent")
    try:
        result = intents.set_strength(intent_id, strength)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _audit("intent_strength", "intent", intent_id, {"strength": strength})
    return {"intent": result["intent"]}


# --------------------------------------------------------------------------- #
# customers, referrals, conversations
# --------------------------------------------------------------------------- #
@router.get("/customers")
def list_customers(search: str = "", limit: int = 100) -> dict[str, Any]:
    return {"customers": customers.list_customers(search, limit)}


@router.get("/customers/{customer_id}")
def customer_detail(customer_id: str) -> dict[str, Any]:
    customer = customers.get(customer_id)
    if customer is None:
        raise HTTPException(404, "Unknown customer")
    return {
        "customer": customer,
        "intents": [
            {**r, "specifications": loads(r.get("specifications_json"), {})}
            for r in intents.list_intents(limit=50)
            if r["customer_id"] == customer_id
        ],
        "referrals": referrals.for_customer(customer_id),
        "notifications": notifications.history(customer_id=customer_id, limit=25),
    }


@router.get("/referrals")
def referral_performance(limit: int = 25) -> dict[str, Any]:
    return {"leaderboard": referrals.leaderboard(limit), "stats": referrals.stats()}


@router.get("/conversations")
def list_conversations(limit: int = 50) -> dict[str, Any]:
    rows = query(
        "SELECT c.id, c.session_id, c.stage, c.created_at, c.updated_at, c.intent_id, "
        "cu.name AS customer_name, cu.mobile AS customer_mobile "
        "FROM conversations c LEFT JOIN customers cu ON cu.id = c.customer_id "
        "ORDER BY c.updated_at DESC LIMIT ?",
        (limit,),
    )
    return {"conversations": [dict(r) for r in rows]}


@router.get("/conversations/{session_id}")
def conversation_detail(session_id: str) -> dict[str, Any]:
    record = conversation.get(session_id)
    if record is None:
        raise HTTPException(404, "Unknown conversation")
    return {
        "conversation": {
            **record,
            "messages": conversation.transcript(record),
            "extracted_information": conversation.state_of(record),
        }
    }


# --------------------------------------------------------------------------- #
# maintenance
# --------------------------------------------------------------------------- #
@router.post("/maintenance/recalculate-all")
def recalculate_all() -> dict[str, Any]:
    outcomes = groups.recalculate_all()
    return {
        "groups": len(outcomes),
        "price_changes": sum(1 for o in outcomes if o["price_changed"]),
    }


@router.post("/maintenance/run-jobs")
def run_jobs(request: Request) -> dict[str, Any]:
    from ..worker import run_once

    return run_once(str(request.base_url).rstrip("/"))


@router.get("/audit")
def audit_log(limit: int = 100) -> dict[str, Any]:
    rows = query("SELECT * FROM admin_audit ORDER BY created_at DESC LIMIT ?", (limit,))
    return {"entries": [{**dict(r), "detail": loads(r["detail"], {})} for r in rows]}


@router.get("/slab-templates")
def slab_templates() -> dict[str, Any]:
    rows = query(
        "SELECT product_key, minimum_qty, maximum_qty, price, price_status FROM pricing_slabs "
        "WHERE group_id IS NULL ORDER BY product_key, minimum_qty"
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["product_key"], []).append(dict(row))
    return {"templates": grouped}
