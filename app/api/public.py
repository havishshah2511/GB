"""Customer-facing API (spec section 29). No authentication: the chatbot is the
only client, and the mobile number is the identity."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import catalog
from ..db import loads
from ..models import (
    ChatMessageIn, IntentIn, IntentPatch, JoinGroupIn, ReconfirmIn, ReferralIn,
)
from ..services import (
    conversation, groups, intents, matching, notifications, pricing, referrals,
)

router = APIRouter(prefix="/api", tags=["public"])


def base_url(request: Request) -> str:
    """Absolute origin for share and status links.

    Behind a TLS-terminating proxy the request itself looks like plain http, so
    an unqualified base_url would hand customers http:// links that browsers
    then block as mixed content. X-Forwarded-Proto is the proxy's answer.
    """
    origin = str(request.base_url).rstrip("/")
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    if forwarded == "https" and origin.startswith("http://"):
        origin = "https://" + origin[len("http://"):]
    return origin


def _group_or_404(group_ref: str) -> dict[str, Any]:
    group = groups.resolve(group_ref)
    if group is None:
        raise HTTPException(404, f"Unknown group {group_ref}")
    return group


def _intent_or_404(intent_id: str) -> dict[str, Any]:
    intent = intents.get_full(intent_id)
    if intent is None:
        raise HTTPException(404, f"Unknown intent {intent_id}")
    return intent


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
@router.post("/chat/message")
def chat_message(payload: ChatMessageIn, request: Request) -> dict[str, Any]:
    return conversation.handle(
        payload.session_id,
        payload.message,
        referral_code=payload.ref,
        group_code=payload.group,
        base_url=base_url(request),
    )


@router.get("/chat/{session_id}")
def chat_history(session_id: str) -> dict[str, Any]:
    record = conversation.get(session_id)
    if record is None:
        raise HTTPException(404, "Unknown session")
    return {
        "session_id": session_id,
        "stage": record["stage"],
        "messages": conversation.transcript(record),
        "summary": conversation.summary(conversation.state_of(record)),
    }


@router.get("/chat/{session_id}/live")
def chat_live(session_id: str, request: Request) -> dict[str, Any]:
    """Polled by an open chat window so a merge that happens while the customer
    is still on the page shows up in the same conversation."""
    return conversation.live_updates(session_id, base_url=base_url(request))


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return {
        "categories": [
            {
                "key": c.key,
                "label": c.label,
                "emoji": c.emoji,
                "unit": c.unit,
                "intro": c.intro,
                "quantity_chips": list(c.quantity_chips),
            }
            for c in catalog.all_categories()
        ],
        "quick_options": catalog.quick_options(),
    }


# --------------------------------------------------------------------------- #
# intents
# --------------------------------------------------------------------------- #
@router.post("/intents", status_code=201)
def create_intent(payload: IntentIn, request: Request) -> dict[str, Any]:
    if catalog.get(payload.category) is None:
        raise HTTPException(400, f"Unknown category {payload.category}")
    result = intents.create(
        payload.to_state(),
        conversation_id=payload.conversation_id,
        referral_code=payload.referral_code,
    )
    group = result["group"]
    qty = float(result["intent"]["quantity"] or 0)
    return {
        "intent": intents.to_api(result["intent"]),
        "group": groups.to_api(group, qty),
        "group_created": result["group_created"],
        "match_score": result["match_score"],
        "match_reasons": result["match_reasons"],
        "share": referrals.share_kit(
            group,
            pricing.price_facts(group, qty),
            referrals.ensure(result["customer"]["id"], group["id"])["referral_code"],
            base_url(request),
        ),
    }


@router.get("/intents/{intent_id}")
def get_intent(intent_id: str) -> dict[str, Any]:
    return intents.to_api(_intent_or_404(intent_id))


@router.put("/intents/{intent_id}")
def update_intent(intent_id: str, payload: IntentPatch) -> dict[str, Any]:
    _intent_or_404(intent_id)
    patch = payload.model_dump(exclude_none=True, exclude={"rematch"})
    result = intents.update(intent_id, patch, rematch=payload.rematch)
    out: dict[str, Any] = {"intent": intents.to_api(result["intent"])}
    group = result.get("group") or (result.get("recalculation") or {}).get("group")
    if group:
        out["group"] = groups.to_api(group, float(result["intent"]["quantity"] or 0))
    return out


@router.post("/intents/{intent_id}/match")
def match_intent(intent_id: str) -> dict[str, Any]:
    intent = _intent_or_404(intent_id)
    result = intents.match_and_join(intent_id)
    return {
        "intent_id": intent_id,
        "group": groups.to_api(result["group"], float(intent["quantity"] or 0)),
        "group_created": result["group_created"],
        "match_score": result["match_score"],
        "match_reasons": result["match_reasons"],
        "candidates": matching.explain(intents.get(intent_id) or {}),
    }


@router.post("/intents/{intent_id}/reconfirm")
def reconfirm_intent(intent_id: str, payload: ReconfirmIn) -> dict[str, Any]:
    _intent_or_404(intent_id)
    result = intents.reconfirm(intent_id, payload.new_date, payload.still_interested)
    return {"intent": intents.to_api(result["intent"])}


# --------------------------------------------------------------------------- #
# groups
# --------------------------------------------------------------------------- #
@router.get("/groups/{group_ref}")
def get_group(group_ref: str, qty: float = 0) -> dict[str, Any]:
    return groups.to_api(_group_or_404(group_ref), qty)


@router.get("/groups/{group_ref}/pricing")
def get_group_pricing(group_ref: str, qty: float = 0) -> dict[str, Any]:
    group = _group_or_404(group_ref)
    return {
        "group_id": group["code"],
        "facts": pricing.price_facts(group, qty),
        "slabs": pricing.slab_table(group),
        "supplier_price_confirmed": bool(group["supplier_price_confirmed"]),
    }


@router.post("/groups/{group_ref}/join")
def join_group(group_ref: str, payload: JoinGroupIn) -> dict[str, Any]:
    group = _group_or_404(group_ref)
    intent = _intent_or_404(payload.intent_id)
    outcome = groups.move_intent(payload.intent_id, group["id"])
    return {
        "intent_id": payload.intent_id,
        "group": groups.to_api(outcome["target"]["group"], float(intent["quantity"] or 0)),
    }


@router.post("/groups/{group_ref}/recalculate")
def recalculate_group(group_ref: str) -> dict[str, Any]:
    group = _group_or_404(group_ref)
    outcome = groups.recalculate(group["id"])
    return {
        "group": groups.to_api(outcome["group"]),
        "price_changed": outcome["price_changed"],
        "price_dropped": outcome["price_dropped"],
        "quantity_changed": outcome["quantity_changed"],
        "notifications_queued": len(outcome["notifications"]),
    }


# --------------------------------------------------------------------------- #
# referrals
# --------------------------------------------------------------------------- #
@router.post("/referrals", status_code=201)
def create_referral(payload: ReferralIn, request: Request) -> dict[str, Any]:
    group = _group_or_404(payload.group_id)
    referral = referrals.ensure(payload.customer_id, group["id"])
    return referrals.share_kit(
        group, pricing.price_facts(group), referral["referral_code"], base_url(request)
    )


@router.get("/referrals/{code}")
def get_referral(code: str) -> dict[str, Any]:
    referral = referrals.get_by_code(code)
    if referral is None:
        raise HTTPException(404, "Unknown referral code")
    group = groups.get(referral["group_id"]) if referral["group_id"] else None
    return {
        "referral": referral,
        "group": groups.to_api(group) if group else None,
    }


# --------------------------------------------------------------------------- #
# notification processing (called by the worker or an external scheduler)
# --------------------------------------------------------------------------- #
@router.post("/notifications/process")
def process_notifications(request: Request, limit: int = 100) -> dict[str, Any]:
    consolidated = groups.consolidate()
    reminders = notifications.send_expiry_reminders(base_url(request))
    expired = intents.expire_due()
    dispatched = notifications.dispatch(limit)
    return {
        "groups_merged": consolidated["groups_merged"],
        "expiry_reminders_queued": reminders,
        "intents_expired": expired["expired"],
        "groups_recalculated": expired["groups_recalculated"],
        **dispatched,
    }


@router.get("/notifications")
def list_notifications(group_id: str | None = None, customer_id: str | None = None,
                       limit: int = 50) -> dict[str, Any]:
    return {
        "notifications": [
            {**n, "payload": loads(n.get("payload"), {})}
            for n in notifications.history(group_id, customer_id, limit)
        ],
        "stats": notifications.stats(),
    }
