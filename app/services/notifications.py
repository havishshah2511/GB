"""Notification engine.

Two halves:
  * rules -- decide *whether* an event deserves a message (spec section 20)
  * channels -- deliver it (WhatsApp primary, SMS secondary, email optional)

Messages are always composed from backend pricing facts. Delivery is pluggable:
the default sink writes to the outbox table and the server log, so the whole
loop is observable without third-party credentials.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator

from .. import catalog
from ..config import settings
from ..db import dumps, execute, insert, new_id, now_iso, query, query_one
from ..utils import money, short_date
from . import pricing

log = logging.getLogger("groupbuy.notifications")

CHANNELS = ("whatsapp", "sms", "email")

#: Set while bulk-loading historical or demo data so backfilled quantity
#: changes don't blast every seeded customer with catch-up messages.
_suppressed = False


@contextmanager
def suppressed() -> Iterator[None]:
    global _suppressed
    previous = _suppressed
    _suppressed = True
    try:
        yield
    finally:
        _suppressed = previous


# --------------------------------------------------------------------------- #
# channel adapters
# --------------------------------------------------------------------------- #
def _log_sink(notification: dict[str, Any]) -> bool:
    log.info(
        "[%s] -> %s\n%s",
        notification["channel"].upper(),
        notification.get("to") or notification.get("customer_id"),
        notification["message"],
    )
    return True


#: Swap these for real providers (Meta Cloud API, Gupshup, Twilio, SES...).
#: A sender returns True on success.
SENDERS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "whatsapp": _log_sink,
    "sms": _log_sink,
    "email": _log_sink,
}


def register_sender(channel: str, sender: Callable[[dict[str, Any]], bool]) -> None:
    SENDERS[channel] = sender


# --------------------------------------------------------------------------- #
# outbox
# --------------------------------------------------------------------------- #
def queue(
    customer_id: str | None,
    group_id: str | None,
    kind: str,
    message: str,
    channel: str | None = None,
    intent_id: str | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any] | None:
    """Insert into the outbox. Returns None when suppressed (duplicate or
    over the per-customer rate limit)."""
    if _suppressed:
        return None
    channel = channel or settings.NOTIFY_DEFAULT_CHANNEL
    if dedupe_key and query_one("SELECT id FROM notifications WHERE dedupe_key = ?", (dedupe_key,)):
        return None
    if customer_id and group_id and kind != "admin_broadcast" and _over_rate_limit(customer_id, group_id):
        log.debug("rate limited: %s / %s / %s", customer_id, group_id, kind)
        return None

    record = {
        "id": new_id("NTF", width=6, start=1),
        "customer_id": customer_id,
        "group_id": group_id,
        "intent_id": intent_id,
        "type": kind,
        "channel": channel,
        "message": message,
        "payload": dumps(payload or {}),
        "status": "queued",
        "dedupe_key": dedupe_key,
        "created_at": now_iso(),
        "sent_at": None,
    }
    insert("notifications", record)
    return record


def _over_rate_limit(customer_id: str, group_id: str) -> bool:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat()
    row = query_one(
        "SELECT COUNT(*) AS n FROM notifications WHERE customer_id = ? AND group_id = ? "
        "AND created_at >= ?",
        (customer_id, group_id, since),
    )
    return bool(row) and int(row["n"]) >= settings.NOTIFY_MAX_PER_CUSTOMER_PER_DAY


def pending(limit: int = 100) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in query(
            "SELECT n.*, c.mobile AS to_mobile, c.name AS to_name FROM notifications n "
            "LEFT JOIN customers c ON c.id = n.customer_id "
            "WHERE n.status = 'queued' ORDER BY n.created_at LIMIT ?",
            (limit,),
        )
    ]


def dispatch(limit: int = 100) -> dict[str, Any]:
    """Deliver queued messages through the configured channel adapters."""
    sent = failed = 0
    for row in pending(limit):
        sender = SENDERS.get(row["channel"], _log_sink)
        payload = {**row, "to": row.get("to_mobile")}
        try:
            ok = bool(sender(payload))
        except Exception:  # a broken provider must not stall the outbox
            log.exception("notification %s failed", row["id"])
            ok = False
        execute(
            "UPDATE notifications SET status = ?, sent_at = ? WHERE id = ?",
            ("sent" if ok else "failed", now_iso() if ok else None, row["id"]),
        )
        sent += ok
        failed += not ok
    return {"sent": sent, "failed": failed}


def history(group_id: str | None = None, customer_id: str | None = None,
            limit: int = 100) -> list[dict[str, Any]]:
    sql = (
        "SELECT n.*, c.name AS customer_name, c.mobile AS customer_mobile, g.code AS group_code "
        "FROM notifications n LEFT JOIN customers c ON c.id = n.customer_id "
        "LEFT JOIN buying_groups g ON g.id = n.group_id WHERE 1 = 1"
    )
    params: list[Any] = []
    if group_id:
        sql += " AND n.group_id = ?"
        params.append(group_id)
    if customer_id:
        sql += " AND n.customer_id = ?"
        params.append(customer_id)
    sql += " ORDER BY n.created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in query(sql, params)]


# --------------------------------------------------------------------------- #
# message templates (spec sections 19, 21, 22, 25)
# --------------------------------------------------------------------------- #
def _share_line(group: dict[str, Any], customer_id: str) -> str:
    from . import referrals

    referral = referrals.ensure(customer_id, group["id"])
    return referrals.share_url(group["code"], referral["referral_code"])


def price_drop_message(group: dict[str, Any], before: dict[str, Any],
                       member: dict[str, Any]) -> str:
    category = catalog.require(group["product_category"])
    qty = float(member.get("quantity") or 0)
    facts = pricing.price_facts(group, qty)
    name = member.get("customer_name") or "there"
    lines = [
        "🎉 Price Drop Alert!",
        "",
        f"Great news, {name}! More buyers have joined your "
        f"{category.spec_description(pricing.spec_of(group))} group in {group['city']}.",
        "",
        f"Previous group quantity: {category.qty_label(float(before['strong_intent_qty'] or 0))}",
        f"New group quantity: {facts['group_quantity_text']}",
        "",
        f"Previous price: {money(before['current_price'])}",
        f"New group price: {facts['current_price_text']}",
        "",
        f"You now save {facts['saving_per_unit_text']} per {category.unit}.",
    ]
    if qty:
        lines.append(f"Your requirement: {facts['your_quantity_text']} → total saving {facts['your_saving_text']}")
    if facts.get("next_target_qty"):
        lines += [
            "",
            f"Next price level is at {facts['next_target_text']} — only {facts['gap_text']} more.",
            "Know someone planning to buy? Share this link 👇",
            _share_line(group, member["customer_id"]),
        ]
    if not group.get("supplier_price_confirmed"):
        lines += ["", "(Indicative group price — final rate confirmed once the supplier quote is locked.)"]
    return "\n".join(lines)


def near_target_message(group: dict[str, Any], member: dict[str, Any]) -> str:
    category = catalog.require(group["product_category"])
    qty = float(member.get("quantity") or 0)
    facts = pricing.price_facts(group, qty)
    lines = [
        "🔥 We're very close!",
        "",
        f"Your {category.spec_description(pricing.spec_of(group))} group now has "
        f"{facts['group_quantity_text']}.",
        f"The next price starts at {facts['next_target_text']}.",
        "",
        f"Only {facts['gap_text']} more needed.",
        "",
        f"Current price: {facts['current_price_text']}",
        f"Possible next price: {facts['next_price_text']}",
        f"You could save another {facts['next_saving_per_unit_text']} per {category.unit}.",
        "",
        "If you know anyone considering this, now is a great time to invite them 👇",
        _share_line(group, member["customer_id"]),
    ]
    return "\n".join(lines)


def progress_message(group: dict[str, Any], member: dict[str, Any], percent: int) -> str:
    category = catalog.require(group["product_category"])
    qty = float(member.get("quantity") or 0)
    facts = pricing.price_facts(group, qty)
    return "\n".join(
        [
            f"📈 Your buying group is {percent}% of the way to the next price level.",
            "",
            f"{facts['group_label']}",
            f"Combined requirement: {facts['group_quantity_text']}",
            f"Current group price: {facts['current_price_text']}",
            f"Next level: {facts['next_target_text']} → {facts['next_price_text']}",
            f"Still needed: {facts['gap_text']}",
            "",
            "Invite someone and lower everyone's price 👇",
            _share_line(group, member["customer_id"]),
        ]
    )


def referral_joined_message(referrer: dict[str, Any], group: dict[str, Any],
                            added_qty: float) -> str:
    category = catalog.require(group["product_category"])
    facts = pricing.price_facts(group, 0)
    lines = [
        "🎉 Someone you invited has joined!",
        "",
        f"They added {category.qty_label(added_qty)} to the group.",
        f"Your buying group has now reached {facts['group_quantity_text']}.",
        f"Current group price: {facts['current_price_text']}",
    ]
    if facts.get("next_target_qty"):
        lines.append(f"Next level at {facts['next_target_text']} — {facts['gap_text']} to go.")
    return "\n".join(lines)


def expiry_reminder_message(intent: dict[str, Any], base_url: str = "") -> str:
    category = catalog.require(intent["category"])
    name = intent.get("customer_name") or "there"
    when = short_date(intent.get("desired_purchase_date") or intent.get("maximum_purchase_date"))
    base = settings.base_url(base_url)
    return "\n".join(
        [
            f"Hi {name},",
            "",
            f"You earlier told us you were planning to purchase "
            f"{category.qty_label(float(intent['quantity'] or 0))} around {when}.",
            "Are you still interested?",
            "",
            f"✅ Yes, still interested: {base}/r/{intent['id']}/yes",
            f"📅 Change purchase date: {base}/r/{intent['id']}/reschedule",
            f"❌ No longer required: {base}/r/{intent['id']}/no",
        ]
    )


# --------------------------------------------------------------------------- #
# rules engine
# --------------------------------------------------------------------------- #
def _slab_key(group: dict[str, Any]) -> str:
    return f"{group['current_slab_min_qty']}@{group['current_price']}"


def _progress_percent(group: dict[str, Any]) -> int | None:
    """How far the group has travelled through its current slab, toward the
    next target."""
    floor = group.get("current_slab_min_qty")
    target = group.get("next_target_qty")
    qty = float(group.get("strong_intent_qty") or 0)
    if not target or floor is None or target <= floor:
        return None
    return int(round(100 * (qty - float(floor)) / (float(target) - float(floor))))


def on_group_changed(group: dict[str, Any], before: dict[str, Any],
                     price_dropped: bool,
                     exclude_intent_id: str | None = None) -> list[dict[str, Any]]:
    """Called by groups.recalculate(). Decides which members hear about it."""
    from . import groups as groups_service

    members = [
        m for m in groups_service.notifiable_members(group["id"])
        if m["id"] != exclude_intent_id
    ]
    if not members:
        return []

    queued: list[dict[str, Any]] = []

    if price_dropped:
        for member in members:
            note = queue(
                member["customer_id"], group["id"], "price_drop",
                price_drop_message(group, before, member),
                intent_id=member["id"],
                payload={"slab": _slab_key(group), "previous_price": before["current_price"]},
                dedupe_key=f"price_drop:{group['id']}:{member['customer_id']}:{_slab_key(group)}",
            )
            if note:
                queued.append(note)
        return queued

    # No price change -- consider proximity nudges.
    gap = None
    if group.get("next_target_qty") is not None:
        gap = float(group["next_target_qty"]) - float(group.get("strong_intent_qty") or 0)
    percent = _progress_percent(group)
    before_percent = _progress_percent(before)

    if gap is not None and 0 < gap <= settings.NOTIFY_NEAR_TARGET_GAP:
        for member in members:
            note = queue(
                member["customer_id"], group["id"], "near_target",
                near_target_message(group, member),
                intent_id=member["id"],
                payload={"gap": gap, "slab": _slab_key(group)},
                dedupe_key=f"near_target:{group['id']}:{member['customer_id']}:{_slab_key(group)}:{int(gap)}",
            )
            if note:
                queued.append(note)
        return queued

    if percent is None:
        return queued
    for step in sorted(settings.NOTIFY_PROGRESS_STEPS):
        if percent >= step and (before_percent is None or before_percent < step):
            for member in members:
                note = queue(
                    member["customer_id"], group["id"], "progress",
                    progress_message(group, member, step),
                    intent_id=member["id"],
                    payload={"percent": step, "slab": _slab_key(group)},
                    dedupe_key=f"progress:{group['id']}:{member['customer_id']}:{_slab_key(group)}:{step}",
                )
                if note:
                    queued.append(note)
            break
    return queued


def referral_joined(referral: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any] | None:
    from . import groups as groups_service

    group = groups_service.get(referral["group_id"]) if referral.get("group_id") else None
    if group is None or not referral.get("referrer_customer_id"):
        return None
    return queue(
        referral["referrer_customer_id"], group["id"], "referral_joined",
        referral_joined_message(referral, group, float(intent.get("quantity") or 0)),
        payload={"referral_code": referral["referral_code"], "intent_id": intent.get("id")},
        dedupe_key=f"referral_joined:{referral['referral_code']}:{intent.get('id')}",
    )


def send_expiry_reminders(base_url: str = "") -> int:
    from . import intents as intents_service

    count = 0
    for intent in intents_service.reconfirmation_due():
        if not intent.get("customer_mobile"):
            continue
        note = queue(
            intent["customer_id"], intent.get("group_id"), "expiry_reminder",
            expiry_reminder_message(intent, base_url),
            intent_id=intent["id"],
            dedupe_key=f"expiry:{intent['id']}",
        )
        intents_service.mark_reconfirm_sent(intent["id"])
        count += bool(note)
    return count


def broadcast(group_id: str, message: str, channel: str | None = None) -> int:
    """Admin-triggered message to every active member of a group."""
    from . import groups as groups_service

    sent = 0
    for member in groups_service.notifiable_members(group_id):
        note = queue(
            member["customer_id"], group_id, "admin_broadcast", message,
            channel=channel, intent_id=member["id"],
            dedupe_key=f"broadcast:{group_id}:{member['customer_id']}:{now_iso()}",
        )
        sent += bool(note)
    return sent


def stats() -> dict[str, Any]:
    row = query_one(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END), 0) AS sent, "
        "COALESCE(SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END), 0) AS queued, "
        "COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed "
        "FROM notifications"
    )
    return dict(row) if row else {"total": 0, "sent": 0, "queued": 0, "failed": 0}
