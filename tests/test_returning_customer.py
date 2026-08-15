"""Returning buyers, the status link, and live in-chat group updates."""
from __future__ import annotations

from app.services import conversation, customers, intents

from conftest import answer_all

AC_ANSWERS = {
    "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
    "preferred_brand": "Daikin", "brand_flexible": "yes",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 7 days", "can_wait": "yes",
    "name": "Rahul", "mobile": "9876511111",
}


def cards(reply, kind):
    return [m["card"] for m in reply["messages"] if m.get("card", {}).get("type") == kind]


def texts(reply):
    return "\n".join(m.get("text", "") for m in reply["messages"])


# --------------------------------------------------------------------------- #
# first visit
# --------------------------------------------------------------------------- #
def test_first_time_buyer_is_not_interrupted(chat):
    reply = answer_all(chat, "r1", "I need 2 AC", AC_ANSWERS)
    assert reply["done"] is True
    assert "Welcome back" not in texts(reply)
    assert reply["summary"]["intent_id"] is not None


def test_completed_chat_hands_over_a_status_link(chat):
    reply = answer_all(chat, "r2", "I need 2 AC", AC_ANSWERS)
    status = cards(reply, "status")
    assert status, "no status card at the end of the chat"
    assert "/my/" in status[0]["url"]
    assert status[0]["rows"], "status card lists no requests"


def test_status_link_is_also_sent_to_the_mobile(chat):
    answer_all(chat, "r3", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876511333"})
    customer = customers.by_mobile("9876511333")
    outbox = [n for n in _notifications(customer["id"]) if n["type"] == "status_link"]
    assert outbox, "status link was never queued for delivery"
    assert "/my/" in outbox[0]["message"]


def _notifications(customer_id):
    from app.services import notifications

    return notifications.history(customer_id=customer_id)


# --------------------------------------------------------------------------- #
# second visit
# --------------------------------------------------------------------------- #
def test_known_mobile_offers_new_or_past(chat):
    answer_all(chat, "r4a", "I need 2 AC", AC_ANSWERS)

    chat("r4b", "")
    reply = chat("r4b", "I need AC")
    assert reply["question"]["slot"] == "mobile"

    reply = chat("r4b", AC_ANSWERS["mobile"])
    assert reply["question"]["slot"] == "_returning_choice"
    assert "Welcome back" in texts(reply)
    assert "Rahul" in texts(reply)
    values = {c["value"] for c in reply["chips"]}
    assert {"new", "past"} <= values


def test_choosing_past_returns_the_status_link_and_not_a_new_intent(chat):
    answer_all(chat, "r5a", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876511555"})
    before = len(intents.list_by_customer(customers.by_mobile("9876511555")["id"]))

    chat("r5b", "")
    chat("r5b", "I need AC")
    chat("r5b", "9876511555")
    reply = chat("r5b", "past")

    status = cards(reply, "status")
    assert status, "no status card returned"
    assert "/my/" in status[0]["url"]
    assert reply["summary"]["intent_id"] is None

    after = len(intents.list_by_customer(customers.by_mobile("9876511555")["id"]))
    assert after == before, "a duplicate intent was created"


def test_choosing_new_continues_the_full_flow(chat):
    answer_all(chat, "r6a", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876511666"})
    customer = customers.by_mobile("9876511666")

    chat("r6b", "")
    chat("r6b", "I need 100 kg basmati rice")
    reply = chat("r6b", "9876511666")
    assert reply["question"]["slot"] == "_returning_choice"

    reply = chat("r6b", "new")
    # The name is already known, so it is never asked again.
    for _ in range(14):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        assert question["slot"] != "name", "asked a known customer for their name"
        reply = chat("r6b", question["chips"][0]["value"] if question["chips"] else "Ahmedabad")

    assert reply["done"] is True
    records = intents.list_by_customer(customer["id"])
    assert len(records) == 2
    assert {r["category"] for r in records} == {"AC", "RICE"}


# --------------------------------------------------------------------------- #
# the status page
# --------------------------------------------------------------------------- #
def test_status_page_lists_requests_and_their_group_position(client, chat):
    answer_all(chat, "r7", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876511777"})
    customer = customers.by_mobile("9876511777")
    status_token = customers.ensure_status_token(customer["id"])

    page = client.get(f"/my/{status_token}")
    assert page.status_code == 200
    assert "Your requests" in page.text
    assert "Ahmedabad" in page.text
    assert "Buyers together need" in page.text
    assert "noindex" in page.text


def test_unknown_status_token_reveals_nothing(client):
    page = client.get("/my/definitely-not-a-real-token")
    assert page.status_code == 200
    assert "Link not found" in page.text


# --------------------------------------------------------------------------- #
# live merge updates
# --------------------------------------------------------------------------- #
def test_another_buyer_merging_shows_up_in_the_open_chat(chat):
    answer_all(chat, "r8", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876511888"})

    # Nothing has changed yet.
    assert conversation.live_updates("r8")["changed"] is False

    # A second buyer with a compatible requirement joins the same group.
    answer_all(chat, "r8b", "I need 4 AC",
               {**AC_ANSWERS, "mobile": "9876511889", "name": "Meera"})

    update = conversation.live_updates("r8", base_url="http://testserver")
    assert update["changed"] is True
    blurb = "\n".join(m.get("text", "") for m in update["messages"])
    assert "merged into your group" in blurb or "Price drop" in blurb
    assert any(m.get("card", {}).get("type") == "group" for m in update["messages"])

    # The update is consumed once -- polling again is quiet.
    assert conversation.live_updates("r8")["changed"] is False


def test_live_update_is_appended_to_the_stored_transcript(chat):
    answer_all(chat, "r9", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876511999"})
    answer_all(chat, "r9b", "I need 6 AC",
               {**AC_ANSWERS, "mobile": "9876512000", "name": "Karan"})

    conversation.live_updates("r9", base_url="http://testserver")
    record = conversation.get("r9")
    assert any(m.get("live") for m in conversation.transcript(record))


def test_live_endpoint_is_quiet_for_an_unknown_session(client):
    body = client.get("/api/chat/nope/live").json()
    assert body["changed"] is False
    assert body["messages"] == []
