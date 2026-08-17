"""Steering commands must work at ANY point in the conversation.

Reported bug: mid-flow "plz cancel my current request" / "show me my old
request" were swallowed by the slot extractor and answered with
"Sorry, I didn't quite get that."
"""
from __future__ import annotations

import pytest

from app.nlu import rules
from app.services import customers, intents

from conftest import answer_all

AC_ANSWERS = {
    "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
    "preferred_brand": "Daikin", "brand_flexible": "yes",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 7 days", "can_wait": "yes",
    "name": "Rahul", "mobile": "9876522222",
}


def texts(reply):
    return "\n".join(m.get("text", "") for m in reply["messages"])


def cards(reply, kind):
    return [m["card"] for m in reply["messages"] if m.get("card", {}).get("type") == kind]


def chips(reply):
    return {c["value"] for c in reply.get("chips", [])}


# --------------------------------------------------------------------------- #
# pattern level
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("phrase", [
    "plz cancel my current request",
    "cancel request",
    "cancel my request",
    "please cancel it",
    "I want to cancel my order",
    "remove me",
    "no longer required",
    "not interested",
])
def test_cancel_phrases(phrase):
    assert rules.detect_command(phrase) == "cancel"


@pytest.mark.parametrize("phrase", [
    "show me my old request",
    "show my past orders",
    "can I see my previous requests",
    "my requests",
    "check my order",
    "what's my request status",
    "order status",
    "status of my order",
])
def test_show_past_phrases(phrase):
    assert rules.detect_command(phrase) == "show_past"


@pytest.mark.parametrize("phrase", [
    "change product",
    "I want to change the product",
    "different product",
    "something else",
    "can I switch to rice",
])
def test_change_product_phrases(phrase):
    assert rules.detect_command(phrase) == "change_product"


@pytest.mark.parametrize("phrase", ["exit", "bye", "I'm done", "that's all", "close the chat"])
def test_exit_phrases(phrase):
    assert rules.detect_command(phrase) == "exit"


@pytest.mark.parametrize("phrase", [
    "1.5 Ton", "Split", "Inverter", "Daikin", "Ahmedabad", "2", "yes", "Within 7 days",
])
def test_ordinary_answers_are_not_commands(phrase):
    assert rules.detect_command(phrase) is None


# --------------------------------------------------------------------------- #
# mid-conversation, the exact reported failure
# --------------------------------------------------------------------------- #
def test_cancel_mid_flow_is_not_treated_as_an_answer(chat):
    chat("c1", "")
    chat("c1", "I need 2 AC")
    chat("c1", "9876522001")
    reply = chat("c1", "1.5 Ton")
    assert reply["question"]["slot"] == "ac_type"

    reply = chat("c1", "plz cancel my current request")
    assert "didn't quite get that" not in texts(reply).lower()
    assert reply["question"]["slot"] != "ac_type", "command answered as a spec slot"
    assert "cancel" in texts(reply).lower() or "nothing to cancel" in texts(reply).lower()


def test_show_past_mid_flow_is_answered(chat):
    answer_all(chat, "c2a", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876522002"})

    chat("c2b", "")
    chat("c2b", "I need AC")
    chat("c2b", "9876522002")
    chat("c2b", "new")
    reply = chat("c2b", "show me my old request")

    assert "didn't quite get that" not in texts(reply).lower()
    assert cards(reply, "status"), "no status card returned mid-flow"


def test_show_past_before_we_know_the_customer(chat):
    answer_all(chat, "c3a", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876522003"})

    chat("c3b", "")
    reply = chat("c3b", "show me my old requests")
    assert reply["question"]["slot"] == "mobile", "should ask who they are first"

    reply = chat("c3b", "9876522003")
    assert cards(reply, "status"), "requests not shown after the number landed"


def test_change_product_keeps_the_customer_but_drops_the_product(chat):
    chat("c4", "")
    chat("c4", "I need 2 AC")
    chat("c4", "9876522004")
    chat("c4", "1.5 Ton")
    reply = chat("c4", "actually I want a different product")

    assert reply["question"]["slot"] == "category"
    assert reply["summary"]["category"] is None
    assert reply["summary"]["quantity"] is None
    assert reply["summary"]["mobile"] == "9876522004", "made them re-enter their number"


def test_cancel_removes_the_quantity_from_the_group(chat):
    reply = answer_all(chat, "c5", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876522005"})
    intent_id = reply["summary"]["intent_id"]
    assert intents.get(intent_id)["status"] == "active"

    reply = chat("c5", "cancel my request")
    assert intents.get(intent_id)["status"] == "cancelled"
    assert "cancel" in texts(reply).lower()


def test_exit_at_any_time_closes_gracefully(chat):
    chat("c6", "")
    chat("c6", "I need 2 AC")
    reply = chat("c6", "bye")
    assert "didn't quite get that" not in texts(reply).lower()
    assert reply.get("question") is None


def test_exit_after_completing_reassures_and_links(chat):
    answer_all(chat, "c7", "I need 2 AC", {**AC_ANSWERS, "mobile": "9876522007"})
    reply = chat("c7", "that's all thanks")
    assert cards(reply, "status")
    assert "close this page" in texts(reply).lower()


def test_a_missed_answer_offers_a_way_out(chat):
    chat("c8", "")
    chat("c8", "I need 2 AC")
    chat("c8", "9876522008")
    reply = chat("c8", "qwertyuiop")          # unparseable
    assert {"cancel my request", "change product"} <= chips(reply), \
        "no escape route offered after a miss"


def test_cancel_with_several_requests_asks_which(chat):
    mobile = "9876522009"
    answer_all(chat, "c9a", "I need 2 AC", {**AC_ANSWERS, "mobile": mobile})
    answer_all(chat, "c9b", "I need 100 kg basmati rice",
               {**AC_ANSWERS, "mobile": mobile, "grade": "Premium", "usage": "Personal"})

    chat("c9c", "")
    chat("c9c", "I need AC")
    chat("c9c", mobile)
    reply = chat("c9c", "cancel my request")
    assert reply["question"]["slot"] == "_cancel_choice"

    customer = customers.by_mobile(mobile)
    target = intents.list_by_customer(customer["id"], active_only=True)[0]
    reply = chat("c9c", f"cancel {target['id']}")
    assert intents.get(target["id"])["status"] == "cancelled"


def test_a_name_that_looks_like_a_command_is_taken_literally(chat):
    chat("c10", "")
    chat("c10", "I need 2 AC")
    chat("c10", "9876522010")
    reply = chat("c10", "1.5 Ton")
    for _ in range(12):
        question = reply.get("question")
        if not question or question["slot"] == "name":
            break
        reply = chat("c10", question["chips"][0]["value"] if question["chips"] else "Ahmedabad")

    assert reply["question"]["slot"] == "name"
    reply = chat("c10", "Leela")
    assert reply["summary"]["name"] == "Leela"
