"""Notification rules, expiry and the referral loop (spec sections 19-25)."""
from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.db import execute, today
from app.services import groups, intents, notifications, referrals


def make_intent(**overrides):
    state = {
        "category": "AC", "quantity": 2, "city": "Ahmedabad", "area": "Satellite",
        "name": "Buyer", "mobile": "9800000001",
        "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
        "preferred_brand": "No Preference", "brand_flexible": True,
        "desired_purchase_date": str(today() + timedelta(days=7)),
        "maximum_purchase_date": str(today() + timedelta(days=17)),
        "can_wait": True,
    }
    state.update(overrides)
    return intents.create(state)


def kinds(group_id):
    return [n["type"] for n in notifications.history(group_id=group_id)]


def test_price_drop_notifies_existing_members_but_not_the_joiner():
    first = make_intent(quantity=4, mobile="9800001001", name="Neha")
    group_id = first["group"]["id"]
    joiner = make_intent(quantity=8, mobile="9800001002", name="Vikram")
    assert joiner["group"]["id"] == group_id

    sent = notifications.history(group_id=group_id)
    drops = [n for n in sent if n["type"] == "price_drop"]
    assert drops, "no price-drop notification queued"
    assert all(n["customer_mobile"] != "9800001002" for n in drops), \
        "the buyer who just saw the result in chat was messaged too"
    assert "Price Drop Alert" in drops[0]["message"]
    assert "₹37,000" in drops[0]["message"]      # 4 + 8 = 12 units -> 11-20 slab


def test_price_drop_message_carries_backend_numbers_only():
    make_intent(quantity=4, mobile="9800001003", name="Neha")
    make_intent(quantity=8, mobile="9800001004")
    message = [n for n in notifications.history() if n["type"] == "price_drop"][0]["message"]

    assert "Previous group quantity: 4 ACs" in message
    assert "New group quantity: 12 ACs" in message
    assert "₹40,000" in message and "₹37,000" in message
    assert "Indicative group price" in message      # never claims a guarantee


def test_near_target_fires_inside_the_configured_gap():
    make_intent(quantity=4, mobile="9800001005")
    result = make_intent(quantity=1, mobile="9800001006")   # 5 units, next slab at 6
    group_id = result["group"]["id"]
    assert groups.get(group_id)["next_target_qty"] == 6
    assert "near_target" in kinds(group_id)


def test_no_duplicate_notifications_for_the_same_milestone():
    make_intent(quantity=4, mobile="9800001007")
    result = make_intent(quantity=1, mobile="9800001008")
    group_id = result["group"]["id"]
    before = len(notifications.history(group_id=group_id))

    groups.recalculate(group_id)
    groups.recalculate(group_id)
    assert len(notifications.history(group_id=group_id)) == before


def test_rate_limit_caps_messages_per_customer_per_group():
    make_intent(quantity=4, mobile="9800001009", name="Neha")
    group_id = groups.list_groups()[0]["id"]
    customer_id = groups.members(group_id)[0]["customer_id"]

    queued = [
        notifications.queue(customer_id, group_id, "progress", f"message {i}",
                            dedupe_key=f"unique-{i}")
        for i in range(settings.NOTIFY_MAX_PER_CUSTOMER_PER_DAY + 3)
    ]
    assert sum(1 for q in queued if q) == settings.NOTIFY_MAX_PER_CUSTOMER_PER_DAY


def test_dispatch_marks_messages_sent():
    make_intent(quantity=4, mobile="9800001010")
    make_intent(quantity=8, mobile="9800001011")
    result = notifications.dispatch()
    assert result["sent"] >= 1
    assert result["failed"] == 0
    assert all(n["status"] == "sent" for n in notifications.history())


def test_broadcast_reaches_every_contactable_member():
    make_intent(quantity=4, mobile="9800001012")
    make_intent(quantity=3, mobile="9800001013")
    group_id = groups.list_groups()[0]["id"]
    sent = notifications.broadcast(group_id, "Supplier quote confirmed — please reply YES.")
    assert sent == 2


# --------------------------------------------------------------------------- #
# expiry / reconfirmation
# --------------------------------------------------------------------------- #
def test_expired_intents_drop_out_of_the_group_quantity():
    keeper = make_intent(quantity=10, mobile="9800002001")
    leaver = make_intent(quantity=5, mobile="9800002002")
    group_id = keeper["group"]["id"]
    assert groups.get(group_id)["current_qty"] == 15

    execute(
        "UPDATE purchase_intents SET expires_at = ? WHERE id = ?",
        (str(today() - timedelta(days=1)), leaver["intent"]["id"]),
    )
    outcome = intents.expire_due()
    assert outcome["expired"] == 1
    assert groups.get(group_id)["current_qty"] == 10
    assert intents.get(leaver["intent"]["id"])["status"] == "expired"


def test_reminder_is_sent_before_expiry_and_only_once():
    result = make_intent(quantity=3, mobile="9800002003", name="Rahul")
    execute(
        "UPDATE purchase_intents SET expires_at = ? WHERE id = ?",
        (str(today() + timedelta(days=1)), result["intent"]["id"]),
    )
    assert notifications.send_expiry_reminders("http://testserver") == 1
    assert notifications.send_expiry_reminders("http://testserver") == 0

    reminder = [n for n in notifications.history() if n["type"] == "expiry_reminder"][0]
    assert "still interested" in reminder["message"].lower()
    assert f"/r/{result['intent']['id']}/yes" in reminder["message"]


def test_reconfirmation_extends_the_window_and_reactivates():
    result = make_intent(quantity=3, mobile="9800002004")
    intent_id = result["intent"]["id"]
    intents.set_status(intent_id, "expired")
    assert intents.get(intent_id)["status"] == "expired"

    intents.reconfirm(intent_id, still_interested=True)
    refreshed = intents.get(intent_id)
    assert refreshed["status"] == "active"
    assert refreshed["expires_at"] > str(today())


def test_declining_reconfirmation_cancels_the_intent():
    result = make_intent(quantity=3, mobile="9800002005")
    intents.reconfirm(result["intent"]["id"], still_interested=False)
    assert intents.get(result["intent"]["id"])["status"] == "cancelled"
    assert groups.get(result["group"]["id"])["current_qty"] == 0


# --------------------------------------------------------------------------- #
# referrals
# --------------------------------------------------------------------------- #
def test_referral_attribution_credits_quantity_and_notifies_the_referrer():
    referrer = make_intent(quantity=4, mobile="9800003001", name="Rahul")
    referral = referrals.ensure(referrer["customer"]["id"], referrer["group"]["id"])
    code = referral["referral_code"]

    referrals.record_click(code, "sess-friend")
    referrals.record_chat_started(code, "sess-friend")

    friend = intents.create(
        {
            "category": "AC", "quantity": 2, "city": "Ahmedabad", "area": "Satellite",
            "name": "Friend", "mobile": "9800003002", "capacity": "1.5 Ton",
            "ac_type": "Split", "inverter": "Inverter", "brand_flexible": True,
            "desired_purchase_date": str(today() + timedelta(days=7)),
            "maximum_purchase_date": str(today() + timedelta(days=17)), "can_wait": True,
        },
        referral_code=code,
    )

    updated = referrals.get_by_code(code)
    assert updated["clicks"] == 1
    assert updated["chats_started"] == 1
    assert updated["intents_submitted"] == 1
    assert updated["quantity_generated"] == 2
    assert friend["group"]["id"] == referrer["group"]["id"]

    joined = [n for n in notifications.history() if n["type"] == "referral_joined"]
    assert joined, "referrer was not told their invite worked"
    assert "They added 2 ACs" in joined[0]["message"]


def test_self_referral_is_ignored():
    result = make_intent(quantity=4, mobile="9800003003")
    referral = referrals.ensure(result["customer"]["id"], result["group"]["id"])
    referrals.attribute_intent(referral["referral_code"], intents.get_full(result["intent"]["id"]))
    assert referrals.get_by_code(referral["referral_code"])["quantity_generated"] == 0


def test_share_link_shape():
    result = make_intent(quantity=4, mobile="9800003004")
    referral = referrals.ensure(result["customer"]["id"], result["group"]["id"])
    url = referrals.share_url(result["group"]["code"], referral["referral_code"], "http://testserver")
    assert url == f"http://testserver/join/{result['group']['code']}?ref={referral['referral_code']}"
