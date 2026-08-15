"""Conversation engine (spec sections 2-8, 26)."""
from __future__ import annotations

from conftest import answer_all

from app.services import conversation, intents


def texts(reply):
    return " ".join(m.get("text", "") for m in reply["messages"])


def cards(reply, kind=None):
    found = [m["card"] for m in reply["messages"] if m.get("card")]
    return [c for c in found if kind is None or c["type"] == kind]


def test_opening_offers_both_categories(chat):
    reply = chat("s1", "")
    assert "combining your requirement" in texts(reply)
    labels = [c["label"] for c in reply["chips"]]
    assert any("Air Conditioner" in l for l in labels)
    assert any("Rice" in l for l in labels)


def test_never_asks_for_information_already_given(chat):
    """Spec section 3: the bot must not re-ask product, quantity or brand."""
    chat("s2", "")
    reply = chat("s2", "I need two Daikin 1.5 ton ACs in Ahmedabad next week")

    asked = []
    for _ in range(10):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        asked.append(question["slot"])
        reply = chat("s2", question["chips"][0]["value"] if question["chips"] else "skip")

    for slot in ("category", "quantity", "capacity", "preferred_brand", "city",
                 "desired_purchase_date"):
        assert slot not in asked, f"re-asked {slot} despite it being stated"


def test_ac_flow_reaches_a_group_and_shows_the_full_result(chat):
    reply = answer_all(
        chat, "s3", "I need 2 AC",
        {
            "quantity": "2", "capacity": "1.5 Ton", "ac_type": "Split",
            "inverter": "Inverter", "preferred_brand": "Daikin", "brand_flexible": "yes",
            "city": "Ahmedabad", "area": "Satellite",
            "desired_purchase_date": "Within 15 days", "can_wait": "yes",
            "name": "Rahul", "mobile": "9876543210",
        },
    )
    assert reply["done"] is True
    assert reply["summary"]["intent_id"]
    assert reply["summary"]["group_code"]
    assert cards(reply, "group"), "no group card shown"
    assert cards(reply, "done"), "no completion card shown"

    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["intent_strength"] == "strong_intent"
    assert intent["quantity"] == 2
    assert intent["city"] == "Ahmedabad"


def test_rice_flow_collects_its_own_specification(chat):
    reply = answer_all(
        chat, "s4", "I need 200 kg Basmati",
        {
            "grade": "Premium", "usage": "Restaurant", "brand_preference": "India Gate",
            "brand_flexible": "yes", "city": "Ahmedabad", "area": "Navrangpura",
            "desired_purchase_date": "Within 7 days", "can_wait": "yes",
            "name": "Hotel Rasoi", "mobile": "9876500000",
        },
    )
    assert reply["done"] is True
    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["category"] == "RICE"
    assert intent["quantity"] == 200
    assert intent["unit"] == "kg"
    assert "Basmati" in intent["product"]


def test_mobile_is_asked_straight_after_the_product(chat):
    """The mobile number identifies returning buyers, so it is collected as soon
    as the product is known -- before the rest of the requirement."""
    chat("s5", "")
    reply = chat("s5", "I need 2 AC")
    order = []
    for _ in range(14):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        order.append(question["slot"])
        answers = {"name": "Asha", "mobile": "9876500001"}
        reply = chat("s5", answers.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert "name" in order and "mobile" in order
    assert order.index("mobile") < order.index("name")
    assert order.index("mobile") == 0, f"mobile should lead, got {order}"
    # the name still comes at the very end, once the requirement is understood
    assert order.index("name") >= len(order) - 2


def test_mobile_is_mandatory_before_the_intent_becomes_active(chat):
    chat("s6", "")
    reply = chat("s6", "I need 2 AC 1.5 ton split inverter in Ahmedabad within 7 days")

    # The flow cannot get past the mobile question without a valid number.
    assert reply["question"]["slot"] == "mobile"
    reply = chat("s6", "not telling you")
    assert reply["question"]["slot"] == "mobile", "flow advanced without a mobile"
    assert reply["summary"]["intent_id"] is None

    reply = chat("s6", "9876500002")
    assert reply["summary"]["mobile"] == "9876500002"

    for _ in range(12):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        reply = chat("s6", "Asha" if question["slot"] == "name"
                     else (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert reply["summary"]["intent_id"] is not None


def test_explaining_the_model_does_not_derail_collection(chat):
    chat("s7", "")
    chat("s7", "I need 2 AC")
    reply = chat("s7", "how does this work?")
    assert "more quantity" in texts(reply).lower() or "buying power" in texts(reply).lower()
    assert reply.get("question") is not None, "bot forgot what it was asking"


def test_conversation_survives_a_reload(chat):
    chat("s8", "")
    chat("s8", "I need 3 AC in Ahmedabad")
    resumed = chat("s8", "")
    assert resumed["resumed"] is True
    assert len(resumed["messages"]) >= 3
    assert any(m.get("role") == "user" for m in resumed["messages"])


def test_restart_clears_the_slot_bag(chat):
    chat("s9", "")
    chat("s9", "I need 3 AC in Ahmedabad")
    reply = chat("s9", "start over")
    assert reply["summary"]["quantity"] is None
    assert reply["summary"]["city"] is None


def test_optional_questions_are_dropped_after_two_unhelpful_answers(chat):
    chat("s10", "")
    chat("s10", "I need 2 AC 1.5 ton split inverter in Ahmedabad within 7 days")
    seen = []
    for _ in range(14):
        state = conversation.state_of(conversation.get("s10"))
        question = conversation.next_question(state) or conversation.contact_question(state)
        if question is None:
            break
        seen.append(question.slot)
        chat("s10", "hmm")           # deliberately unhelpful

    optional = [s for s in set(seen) if s not in ("name", "mobile")]
    for slot in optional:
        assert seen.count(slot) <= 2, f"looped on optional slot {slot}: {seen}"
    # The flow still reaches the mandatory contact capture.
    assert "mobile" in seen


def test_essential_questions_are_rephrased_rather_than_repeated(chat):
    chat("s10b", "")
    reply = chat("s10b", "I need 2 AC 1.5 ton split inverter in Ahmedabad within 7 days")
    for _ in range(12):
        state = conversation.state_of(conversation.get("s10b"))
        if state.get("_expecting") == "mobile":
            break
        reply = chat("s10b", "skip")

    original = texts(reply)
    assert "mobile number" in original

    clarified = texts(chat("s10b", "banana"))
    assert clarified != original, "bot repeated the same prompt verbatim"
    assert "10-digit" in clarified, "bot did not rephrase after a bad mobile number"

    # It keeps asking — the number is mandatory — and still accepts a good one.
    accepted = chat("s10b", "9876500009")
    assert accepted["summary"]["mobile"] == "9876500009"


def test_bot_never_states_a_price_before_a_group_exists(chat):
    chat("s11", "")
    reply = chat("s11", "I need 2 AC. What price will I get?")
    assert "₹" not in texts(reply)
