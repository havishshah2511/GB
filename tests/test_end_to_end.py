"""The whole loop, as described in spec sections 1 and 23.

  intent -> group -> quantity up -> price down -> notify -> share -> repeat
"""
from __future__ import annotations

from conftest import answer_all

from app.services import groups, intents, notifications, referrals

AC_ANSWERS = {
    "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
    "preferred_brand": "No Preference", "brand_flexible": "yes",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 15 days", "can_wait": "yes",
}


def buy(chat, session, opening, name, mobile, **extra):
    return answer_all(chat, session, opening, {**AC_ANSWERS, **extra, "name": name, "mobile": mobile})


def cards(reply, kind):
    return [m["card"] for m in reply["messages"] if m.get("card") and m["card"]["type"] == kind]


def test_full_group_buying_loop(chat):
    # --- 1. an 18-unit group already exists (the spec's worked example) ------
    buy(chat, "e2e-a", "I need 8 AC", "Neha", "9811110001")
    buy(chat, "e2e-b", "I need 10 AC", "Vikram", "9811110002")

    group = groups.list_groups()[0]
    assert group["strong_intent_qty"] == 18
    assert group["current_price"] == 37000
    assert group["next_target_qty"] == 21

    # --- 2. a new customer joins: 18 + 2 = 20 (section 12) -------------------
    reply = buy(chat, "e2e-c", "I need 2 AC", "Rahul", "9811110003")
    assert reply["done"] is True

    group_card = cards(reply, "group")[0]
    assert group_card["group_quantity_text"] == "20 ACs"
    assert group_card["current_price_text"] == "₹37,000"
    assert group_card["reference_price_text"] == "₹40,000"
    assert group_card["saving_per_unit_text"] == "₹3,000"      # section 14
    assert group_card["your_saving_text"] == "₹6,000"

    # --- 3. the next target is shown (section 15) ---------------------------
    target = cards(reply, "next_target")[0]
    assert target["next_target_qty"] == 21
    assert target["gap_text"] == "1 AC"
    assert target["next_price_text"] == "₹35,500"
    assert target["next_saving_per_unit_text"] == "₹1,500"
    assert target["your_next_saving_text"] == "₹3,000"

    # --- 4. sharing is offered with a working link (section 16) -------------
    share = cards(reply, "share")[0]
    assert "/join/" in share["url"] and "?ref=" in share["url"]
    assert "wa.me" in share["whatsapp_url"]
    assert cards(reply, "done"), "customer was not told they can leave"

    # --- 5. a friend follows the link and joins (section 22) ----------------
    referral_code = share["referral_code"]
    referrals.record_click(referral_code, "e2e-friend")
    friend = answer_all(
        chat, "e2e-friend", "I need 3 AC",
        {**AC_ANSWERS, "name": "Amit", "mobile": "9811110004"},
    )
    # the chat carries the referral through the landing page
    chat("e2e-friend2", "", referral_code=referral_code, group_code=group["code"])
    assert friend["done"] is True

    updated = groups.get(group["id"])
    assert updated["strong_intent_qty"] == 23           # 20 + 3
    assert updated["current_price"] == 35500            # crossed the 21 threshold
    assert updated["next_target_qty"] == 31

    # --- 6. existing members were told the price dropped (section 19) -------
    drops = [n for n in notifications.history(group_id=group["id"]) if n["type"] == "price_drop"]
    recipients = {n["customer_mobile"] for n in drops}
    assert "9811110001" in recipients and "9811110003" in recipients
    assert "9811110004" not in recipients, "the joiner should not be messaged"

    # The pool crossed two thresholds on the way here (8→18 hit ₹37,000, then
    # 20→23 hit ₹35,500), so assert against the most recent drop specifically.
    # history() is newest-first and tie-breaks on id, so drops[0] is stable.
    latest = drops[0]["message"]
    assert "Price Drop Alert" in latest
    assert "₹35,500" in latest
    assert "/join/" in latest                           # every message re-offers sharing

    # Every active member hears about a price drop -- including someone who was
    # already messaged about the earlier one. Price drops bypass the daily cap.
    dropped_to = {n["customer_mobile"] for n in drops if "₹35,500" in n["message"]}
    assert {"9811110001", "9811110002", "9811110003"} <= dropped_to

    # --- 7. the outbox actually delivers ------------------------------------
    result = notifications.dispatch()
    assert result["failed"] == 0
    assert all(n["status"] == "sent" for n in notifications.history())


def test_referral_attribution_is_recorded_through_the_chatbot(chat):
    seed = buy(chat, "ref-a", "I need 4 AC", "Rahul", "9811120001")
    group_code = seed["summary"]["group_code"]
    share = cards(seed, "share")
    code = share[0]["referral_code"] if share else referrals.leaderboard()[0]["referral_code"]

    # friend lands on the shared link, then completes the flow
    chat("ref-friend", "", referral_code=code, group_code=group_code)
    answer_all(chat, "ref-friend", "I need 2 AC",
               {**AC_ANSWERS, "name": "Priya", "mobile": "9811120002"})

    referral = referrals.get_by_code(code)
    assert referral["chats_started"] == 1
    assert referral["intents_submitted"] == 1
    assert referral["quantity_generated"] == 2

    joined = [n for n in notifications.history() if n["type"] == "referral_joined"]
    assert joined and "They added 2 ACs" in joined[0]["message"]


def test_invitee_inherits_the_group_from_the_shared_link(chat):
    """The link already says which product and city — don't ask again, and
    never let the invitee drift into a group of their own."""
    seed = buy(chat, "inv-a", "I need 18 AC", "Rahul", "9811160001")
    group_code = seed["summary"]["group_code"]
    code = cards(seed, "share")[0]["referral_code"]

    landing = chat("inv-friend", "", referral_code=code, group_code=group_code)
    assert landing["question"]["slot"] == "_landing_confirm"

    reply = chat("inv-friend", "yes")
    assert reply["summary"]["city"] == "Ahmedabad"
    assert reply["summary"]["product"] == "1.5 Ton Split Inverter AC"

    asked = []
    for _ in range(10):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        asked.append(question["slot"])
        answers = {"quantity": "3", "name": "Amit", "mobile": "9811160002",
                   "desired_purchase_date": "Within 15 days", "can_wait": "yes"}
        reply = chat("inv-friend", answers.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert "city" not in asked and "capacity" not in asked
    assert reply["summary"]["group_code"] == group_code, "invitee landed in a different group"
    assert groups.get_by_code(group_code)["strong_intent_qty"] == 21


def test_invitee_wanting_something_else_is_not_forced_into_the_group(chat):
    seed = buy(chat, "inv2-a", "I need 8 AC", "Rahul", "9811170001")
    group_code = seed["summary"]["group_code"]
    code = cards(seed, "share")[0]["referral_code"]

    chat("inv2-friend", "", referral_code=code, group_code=group_code)
    reply = chat("inv2-friend", "Something else")
    assert reply["summary"]["product"] is None
    assert reply["summary"]["city"] is None


def test_filler_answers_never_become_data(chat):
    """'skip' must not become a city and spawn a phantom group."""
    chat("filler-a", "")
    chat("filler-a", "I need 2 AC 1.5 ton split inverter")
    for _ in range(8):
        state = chat("filler-a", "")
        question = state.get("question")
        if not question:
            break
        if question["slot"] == "city":
            reply = chat("filler-a", "skip")
            assert reply["summary"]["city"] is None
            break
        chat("filler-a", question["chips"][0]["value"] if question["chips"] else "skip")

    assert not any(g["city"].lower() in ("skip", "no", "none") for g in groups.list_groups())


def test_rice_and_ac_demand_stay_in_separate_groups(chat):
    buy(chat, "mix-a", "I need 4 AC", "Neha", "9811130001")
    answer_all(chat, "mix-b", "I need 300 kg Basmati rice", {
        "grade": "Premium", "usage": "Restaurant", "brand_preference": "No Preference",
        "city": "Ahmedabad", "area": "Navrangpura",
        "desired_purchase_date": "Within 15 days", "can_wait": "yes",
        "name": "Hotel Rasoi", "mobile": "9811130002",
    })

    all_groups = groups.list_groups()
    assert len(all_groups) == 2
    assert {g["product_category"] for g in all_groups} == {"AC", "RICE"}

    rice = next(g for g in all_groups if g["product_category"] == "RICE")
    assert rice["strong_intent_qty"] == 300
    assert rice["current_price"] == 86          # 250-499 kg slab, premium basmati


def test_expired_demand_leaves_and_the_price_reverts(chat):
    buy(chat, "exp-a", "I need 18 AC", "Neha", "9811140001")
    joiner = buy(chat, "exp-b", "I need 5 AC", "Vikram", "9811140002")
    group_id = groups.list_groups()[0]["id"]
    assert groups.get(group_id)["current_price"] == 35500

    intents.set_status(joiner["summary"]["intent_id"], "expired")
    reverted = groups.get(group_id)
    assert reverted["strong_intent_qty"] == 18
    assert reverted["current_price"] == 37000, "expired quantity still counted"


def test_customer_only_talks_to_the_chatbot_once(chat):
    """After completion the customer needs nothing else — the system contacts
    them. Later messages are handled without restarting the flow."""
    reply = buy(chat, "once-a", "I need 3 AC", "Rahul", "9811150001")
    assert reply["done"] is True

    follow_up = chat("once-a", "any update?")
    assert follow_up["stage"] == "done"
    assert follow_up["summary"]["intent_id"] == reply["summary"]["intent_id"]
    assert "group" in " ".join(m.get("text", "") for m in follow_up["messages"]).lower()

    ready = chat("once-a", "I am ready to buy")
    assert intents.get(reply["summary"]["intent_id"])["intent_strength"] == "ready_to_buy"
    assert "ready to buy" in " ".join(m.get("text", "") for m in ready["messages"]).lower()
