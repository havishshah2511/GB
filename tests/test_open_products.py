"""Any product, not just AC and rice.

The customer names the product, it is normalised into a grouping key, and
buyers wanting the same thing in the same city pool together. Such a group
starts with NO price -- nobody has quoted for it -- and the bot says so instead
of inventing one.
"""
from __future__ import annotations

import pytest

from app import catalog
from app.services import conversation, groups, intents, notifications, pricing
from app.utils import detect_unit, normalise_product, singular

from conftest import answer_all

BASE = {
    "city": "Vadodara", "area": "Alkapuri", "variant": "No preference",
    "brand_preference": "No Preference", "desired_purchase_date": "Within 7 days",
    "can_wait": "yes",
}


def buy(chat, session, opening, name, mobile, **overrides):
    return answer_all(chat, session, opening,
                      {**BASE, **overrides, "name": name, "mobile": mobile})


def cards(reply, kind):
    return [m["card"] for m in reply["messages"] if m.get("card", {}).get("type") == kind]


def texts(reply):
    return "\n".join(m.get("text", "") for m in reply["messages"])


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("2 Office Chairs!", "office chair"),
    ("office chair", "office chair"),
    ("good quality OFFICE CHAIRS", "office chair"),
    ("I need 100 kg cement", "cement"),
    ("LED bulbs", "led bulb"),
    ("50 packaging boxes", "packaging box"),
    ("steel pipes", "steel pipe"),
])
def test_product_names_normalise_to_one_key(raw, expected):
    assert normalise_product(raw) == expected


@pytest.mark.parametrize("word,expected", [
    ("boxes", "box"), ("batteries", "battery"), ("chairs", "chair"),
    ("glass", "glass"), ("bus", "bus"), ("rice", "rice"),
])
def test_singularisation_is_conservative(word, expected):
    assert singular(word) == expected


@pytest.mark.parametrize("text,unit", [
    ("100 kg cement", "kg"), ("50 boxes", "box"), ("20 litres paint", "litre"),
    ("5 office chairs", None),
])
def test_unit_detection(text, unit):
    assert detect_unit(text) == unit


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
def test_a_known_product_still_uses_its_own_flow():
    assert catalog.detect("I need 2 AC") == "AC"
    assert catalog.detect("100 kg basmati") == "RICE"


def test_an_unknown_product_falls_back_to_the_open_category():
    assert catalog.detect("I need 50 office chairs") is None, "not without a prompt"
    assert catalog.detect("I need 50 office chairs", allow_fallback=True) == "GENERAL"


@pytest.mark.parametrize("greeting", ["hi", "hello", "ok", "thanks", "what?", "help"])
def test_conversation_is_not_mistaken_for_a_product(greeting):
    assert catalog.detect(greeting, allow_fallback=True) is None


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #
def test_any_product_can_start_a_group(chat):
    reply = buy(chat, "o1", "I need 50 office chairs", "Ravi", "9000000001")
    assert reply["done"] is True

    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["category"] == "GENERAL"
    assert intent["quantity"] == 50
    # Named from the product catalogue, not from what the buyer typed.
    assert intent["product"] == "Office chairs"


def test_two_phrasings_of_one_product_pool_together(chat):
    buy(chat, "o2", "I need 50 office chairs", "Ravi", "9000000002")
    reply = buy(chat, "o3", "looking for good quality Office Chair",
                "Sunita", "9000000003", quantity="30")

    all_groups = groups.list_groups()
    assert len(all_groups) == 1, f"split into {[g['code'] for g in all_groups]}"
    assert all_groups[0]["strong_intent_qty"] == 80
    assert "80 units" in texts(reply)


def test_the_group_is_labelled_by_the_canonical_product(chat):
    buy(chat, "o4", "looking for good quality Office Chairs", "Ravi", "9000000004")
    group = groups.list_groups()[0]
    # The catalogue's wording wins over "good quality Office Chairs".
    assert pricing.group_label(group) == "Vadodara – Office chairs"


def test_different_products_do_not_pool(chat):
    buy(chat, "o5", "I need 50 office chairs", "A", "9000000005")
    buy(chat, "o6", "I need 50 steel pipes", "B", "9000000006")
    assert len(groups.list_groups()) == 2


def test_the_customers_own_unit_is_used(chat):
    reply = buy(chat, "o7", "I need 100 kg cement", "Ravi", "9000000007")
    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["unit"] == "kg"
    assert intent["quantity"] == 100
    assert "100 kg" in texts(reply)


# --------------------------------------------------------------------------- #
# honesty about price
# --------------------------------------------------------------------------- #
def test_an_unpriced_group_never_shows_a_price(chat):
    reply = buy(chat, "o8", "I need 50 office chairs", "Ravi", "9000000008")

    card = cards(reply, "group")[0]
    assert card["has_pricing"] is False
    assert "current_price" not in card and "current_price_text" not in card
    assert card["pricing_status"] == "awaiting_quote"
    assert "negotiat" in texts(reply) or "supplier quote" in texts(reply)


def test_no_next_target_is_promised_without_slabs(chat):
    reply = buy(chat, "o9", "I need 50 office chairs", "Ravi", "9000000009")
    assert not cards(reply, "next_target"), "cannot promise a target with no price ladder"


def test_pricing_an_open_group_tells_every_member(chat):
    buy(chat, "o10", "I need 50 office chairs", "Ravi", "9000001001")
    buy(chat, "o11", "I need office chair", "Sunita", "9000001002", quantity="30")

    group = groups.list_groups()[0]
    assert group["current_price"] is None

    pricing.replace_group_slabs(group["id"], [
        {"minimum_qty": 1, "maximum_qty": 49, "price": 4200},
        {"minimum_qty": 50, "maximum_qty": 99, "price": 3800},
        {"minimum_qty": 100, "maximum_qty": None, "price": 3400},
    ])
    outcome = groups.recalculate(group["id"])

    assert outcome["price_appeared"] is True
    assert outcome["group"]["current_price"] == 3800

    told = {
        n["customer_mobile"]
        for n in notifications.history(group_id=group["id"])
        if n["type"] == "price_available"
    }
    assert told == {"9000001001", "9000001002"}, "every pooled member must be told"


def test_the_price_message_carries_backend_numbers_only(chat):
    buy(chat, "o12", "I need 50 office chairs", "Ravi", "9000001003")
    group = groups.list_groups()[0]
    pricing.replace_group_slabs(group["id"], [
        {"minimum_qty": 1, "maximum_qty": 99, "price": 4200},
        {"minimum_qty": 100, "maximum_qty": None, "price": 3400},
    ])
    groups.recalculate(group["id"])

    message = next(
        n["message"] for n in notifications.history(group_id=group["id"])
        if n["type"] == "price_available"
    )
    assert "₹4,200" in message
    assert "50 units" in message
    assert "100 units" in message      # the next target


# --------------------------------------------------------------------------- #
# consolidation covers open products too
# --------------------------------------------------------------------------- #
def test_consolidation_pools_open_product_groups(chat):
    buy(chat, "o13", "I need 50 office chairs", "A", "9000001004")
    buy(chat, "o14", "I need 20 office chairs", "B", "9000001005")

    # They already pool; force them apart to prove the sweep heals it.
    first, second = intents.list_intents()[::-1]
    groups.split(groups.get(first["group_id"])["id"], [second["id"]])
    assert len(groups.list_groups()) == 2

    assert groups.consolidate()["groups_merged"] == 1
    assert groups.list_groups()[0]["strong_intent_qty"] == 70
