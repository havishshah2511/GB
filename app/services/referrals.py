"""Referral links and attribution -- the growth loop from spec sections 16 & 22."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..config import settings
from ..db import execute, insert, new_id, now_iso, query, query_one, row_to_dict
from ..utils import token


# --------------------------------------------------------------------------- #
# links
# --------------------------------------------------------------------------- #
def get_by_code(code: str) -> dict[str, Any] | None:
    if not code:
        return None
    return row_to_dict(
        query_one("SELECT * FROM referrals WHERE referral_code = ? COLLATE NOCASE", (code,))
    )


def ensure(customer_id: str, group_id: str) -> dict[str, Any]:
    """One stable code per (customer, group) so a re-shared link keeps its stats."""
    existing = query_one(
        "SELECT * FROM referrals WHERE referrer_customer_id = ? AND group_id = ?",
        (customer_id, group_id),
    )
    if existing:
        return dict(existing)

    code = f"R{token(6)}"
    while get_by_code(code):
        code = f"R{token(6)}"

    record = {
        "id": new_id("REF", width=5, start=1000),
        "referral_code": code,
        "referrer_customer_id": customer_id,
        "referred_customer_id": None,
        "group_id": group_id,
        "quantity_generated": 0,
        "clicks": 0,
        "chats_started": 0,
        "intents_submitted": 0,
        "created_at": now_iso(),
    }
    insert("referrals", record)
    return record


def share_url(group_code: str, referral_code: str, base_url: str = "") -> str:
    base = settings.base_url(base_url)
    return f"{base}/join/{group_code}?ref={referral_code}"


def whatsapp_url(message: str) -> str:
    return f"https://wa.me/?text={quote(message)}"


def share_kit(group: dict[str, Any], facts: dict[str, Any], referral_code: str,
              base_url: str = "") -> dict[str, Any]:
    """Everything the UI needs to render the share block."""
    link = share_url(group["code"], referral_code, base_url)
    gap = facts.get("gap_text") or ""
    if facts.get("next_price_text") and gap:
        pitch = (
            f"I'm buying {facts.get('product', 'this')} through a group-buying pool in "
            f"{group['city']}. We're at {facts.get('group_quantity_text')} and the current "
            f"group price is {facts.get('current_price_text')}. Just {gap} more and it drops "
            f"to {facts.get('next_price_text')}. Join here 👇"
        )
    else:
        pitch = (
            f"I'm buying {facts.get('product', 'this')} through a group-buying pool in "
            f"{group['city']}. More buyers means a better price for everyone. Join here 👇"
        )
    text = f"{pitch}\n{link}"
    return {
        "referral_code": referral_code,
        "url": link,
        "message": text,
        "whatsapp_url": whatsapp_url(text),
    }


# --------------------------------------------------------------------------- #
# event tracking
# --------------------------------------------------------------------------- #
def _event(code: str, event_type: str, session_id: str | None = None,
           intent_id: str | None = None, quantity: float = 0) -> None:
    insert(
        "referral_events",
        {
            "id": new_id("RVT", width=6, start=1),
            "referral_code": code,
            "event_type": event_type,
            "session_id": session_id,
            "intent_id": intent_id,
            "quantity": quantity,
            "created_at": now_iso(),
        },
    )


def record_click(code: str, session_id: str | None = None) -> dict[str, Any] | None:
    referral = get_by_code(code)
    if referral is None:
        return None
    execute("UPDATE referrals SET clicks = clicks + 1 WHERE id = ?", (referral["id"],))
    _event(referral["referral_code"], "click", session_id)
    return get_by_code(code)


def record_chat_started(code: str, session_id: str | None = None) -> dict[str, Any] | None:
    referral = get_by_code(code)
    if referral is None:
        return None
    already = query_one(
        "SELECT id FROM referral_events WHERE referral_code = ? AND event_type = 'chat_started' "
        "AND session_id = ?",
        (referral["referral_code"], session_id),
    )
    if already:
        return referral
    execute("UPDATE referrals SET chats_started = chats_started + 1 WHERE id = ?", (referral["id"],))
    _event(referral["referral_code"], "chat_started", session_id)
    return get_by_code(code)


def attribute_intent(code: str, intent: dict[str, Any]) -> dict[str, Any] | None:
    """Credit a submitted intent to the referrer and notify them."""
    referral = get_by_code(code)
    if referral is None or not intent:
        return None
    if intent.get("customer_id") == referral["referrer_customer_id"]:
        return referral  # never self-refer

    already = query_one(
        "SELECT id FROM referral_events WHERE event_type = 'intent_submitted' AND intent_id = ?",
        (intent["id"],),
    )
    if already:
        return referral

    quantity = float(intent.get("quantity") or 0)
    execute(
        "UPDATE referrals SET intents_submitted = intents_submitted + 1, "
        "quantity_generated = quantity_generated + ?, "
        "referred_customer_id = COALESCE(referred_customer_id, ?) WHERE id = ?",
        (quantity, intent.get("customer_id"), referral["id"]),
    )
    execute(
        "UPDATE purchase_intents SET referral_id = ? WHERE id = ?",
        (referral["id"], intent["id"]),
    )
    _event(referral["referral_code"], "intent_submitted", None, intent["id"], quantity)

    from . import notifications

    notifications.referral_joined(get_by_code(code) or referral, intent)
    return get_by_code(code)


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def for_customer(customer_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in query(
            "SELECT r.*, g.code AS group_code FROM referrals r "
            "LEFT JOIN buying_groups g ON g.id = r.group_id "
            "WHERE r.referrer_customer_id = ? ORDER BY r.created_at DESC",
            (customer_id,),
        )
    ]


def leaderboard(limit: int = 25) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in query(
            "SELECT r.*, c.name AS referrer_name, c.mobile AS referrer_mobile, "
            "g.code AS group_code FROM referrals r "
            "LEFT JOIN customers c ON c.id = r.referrer_customer_id "
            "LEFT JOIN buying_groups g ON g.id = r.group_id "
            "ORDER BY r.quantity_generated DESC, r.intents_submitted DESC, r.clicks DESC "
            "LIMIT ?",
            (limit,),
        )
    ]


def stats() -> dict[str, Any]:
    row = query_one(
        "SELECT COUNT(*) AS links, COALESCE(SUM(clicks), 0) AS clicks, "
        "COALESCE(SUM(chats_started), 0) AS chats, "
        "COALESCE(SUM(intents_submitted), 0) AS intents, "
        "COALESCE(SUM(quantity_generated), 0) AS qty FROM referrals"
    )
    data = dict(row) if row else {"links": 0, "clicks": 0, "chats": 0, "intents": 0, "qty": 0}
    clicks = float(data.get("clicks") or 0)
    data["conversion_rate"] = round(100 * float(data.get("intents") or 0) / clicks, 1) if clicks else 0.0
    return data
