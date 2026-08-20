"""Product taxonomy (from the category brief) and Hinglish understanding."""
from __future__ import annotations

import pytest

from app import catalog
from app.catalog import taxonomy
from app.nlu import rules
from app.services import groups

from conftest import answer_all

BASE = {
    "city": "Ahmedabad", "area": "Satellite", "variant": "No preference",
    "brand_preference": "No Preference", "desired_purchase_date": "Within 7 days",
    "can_wait": "yes",
}


def buy(chat, session, opening, name, mobile, **over):
    return answer_all(chat, session, opening, {**BASE, **over, "name": name, "mobile": mobile})


# --------------------------------------------------------------------------- #
# taxonomy
# --------------------------------------------------------------------------- #
def test_the_brief_loaded():
    stats = taxonomy.stats()
    assert stats["families"] > 90, stats
    assert stats["products"] > 1000, stats
    assert stats["events"] > 5, "procurement events should be kept separately"


@pytest.mark.parametrize("text,product,family_word", [
    ("20 cassette ac", "Cassette AC", "HVAC"),
    ("I need MCB", "MCBs", "ELECTRICAL"),
    ("solar panels", "Solar panels", "SOLAR"),
    ("office chairs", "Office chairs", "FURNITURE"),
    ("commercial oven", "Commercial ovens", "KITCHEN"),
    ("100 corrugated boxes", "Corrugated boxes", "PACKAGING"),
    ("storage racks", "Storage racks", "MATERIAL HANDLING"),
])
def test_products_resolve_to_the_catalogue(text, product, family_word):
    found = taxonomy.match(text)
    assert found is not None, f"{text!r} not recognised"
    assert found.product == product
    assert family_word in found.family


@pytest.mark.parametrize("a,b", [
    ("cassette ac", "Cassette A/C"),
    ("20 cassette AC", "cassete ac"),
    ("mcb", "MCBs"),
    ("solar panel", "Solar Panels"),
])
def test_spellings_of_one_product_share_a_key(a, b):
    ma, mb = taxonomy.match(a), taxonomy.match(b)
    assert ma and mb and ma.key == mb.key, f"{a!r} vs {b!r}"


def test_an_unknown_product_is_not_forced_into_the_catalogue():
    assert taxonomy.match("purple widget frobnicator") is None
    # ...but it still gets a usable grouping name.
    assert taxonomy.canonical_product("purple widget frobnicator")


# --------------------------------------------------------------------------- #
# routing stays consistent
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("I need 2 AC", "AC"),
    ("2 split ac", "AC"),
    ("window ac", "AC"),
    ("100 kg basmati", "RICE"),
    # The AC flow asks split-or-window and prices off split slabs, so other
    # air conditioning goes to the open-ended category rather than being
    # priced off the wrong table.
    ("mujhe 20 cassette AC chahiye", "GENERAL"),
    ("15 cassette a/c", "GENERAL"),
    ("ductable ac", "GENERAL"),
    ("VRF system", "GENERAL"),
    ("20 chillers", "GENERAL"),
])
def test_routing(text, expected):
    assert catalog.detect(text, allow_fallback=True) == expected


def test_the_same_product_never_routes_two_ways():
    """A spelling difference must not change which flow a product enters."""
    for pair in [("cassette AC", "cassette a/c"), ("split AC", "split a/c")]:
        first = catalog.detect(pair[0], allow_fallback=True)
        second = catalog.detect(pair[1], allow_fallback=True)
        assert first == second, f"{pair} routed to {first} and {second}"


# --------------------------------------------------------------------------- #
# Hinglish
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,qty", [
    ("do ac chahiye", 2), ("paanch chairs", 5), ("das boxes", 10),
    ("bees cassette ac", 20), ("sau kg", 100), ("ek hazaar", 1000),
])
def test_hinglish_numbers(text, qty):
    assert rules.extract_quantity(text, catalog.get("GENERAL")) == qty


@pytest.mark.parametrize("text,command", [
    ("cancel karo", "cancel"),
    ("nahi chahiye", "cancel"),
    ("band karo", "cancel"),
    ("purana order dikhao", "show_past"),
    ("mera order dikhao", "show_past"),
    ("status batao", "show_past"),
    ("dusra product chahiye", "change_product"),
    ("kuch aur", "change_product"),
    ("bas ho gaya", "exit"),
    ("shukriya", "exit"),
])
def test_hinglish_commands(text, command):
    assert rules.detect_command(text) == command


@pytest.mark.parametrize("text", ["ye kya hai", "kaise kaam karta hai", "samjhao"])
def test_hinglish_questions_are_explained(text):
    assert rules.detect_message_intent(text) == "explain"


@pytest.mark.parametrize("text,expected", [
    ("haan", True), ("ji haan", True), ("bilkul", True), ("theek hai", True),
    ("nahi", False), ("nai", False), ("bilkul nahi", False),
])
def test_hinglish_yes_no(text, expected):
    assert rules.extract_bool(text) is expected


@pytest.mark.parametrize("text,days", [
    ("abhi", 0), ("aaj", 0), ("kal", 1), ("parso", 2),
    ("agle hafte", 7), ("agle mahine", 30),
])
def test_hinglish_timing(text, days):
    from app.db import today

    when, relative = rules.extract_date(text)
    assert relative == days
    assert when == today() + __import__("datetime").timedelta(days=days)


def test_a_hinglish_product_request_is_understood():
    slots = rules.extract("mujhe 20 cassette AC chahiye", {}, expecting="category")
    assert slots.get("category") == "GENERAL"
    assert slots.get("quantity") == 20
    assert taxonomy.match(slots["product_name"]).product == "Cassette AC"


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
def test_hinglish_and_english_buyers_of_one_product_pool(chat):
    buy(chat, "t1", "mujhe 20 cassette AC chahiye", "Rakesh", "9812340001")
    buy(chat, "t2", "I need 15 cassette a/c", "Priya", "9812340002")

    from app.services import pricing

    open_groups = groups.list_groups()
    assert len(open_groups) == 1, f"split into {[g['code'] for g in open_groups]}"
    assert open_groups[0]["strong_intent_qty"] == 35
    # The group is named from the catalogue, not from whichever buyer arrived
    # first typing "cassette a/c".
    assert "Cassette AC" in pricing.group_label(open_groups[0])


def test_a_cassette_buyer_is_not_pooled_with_a_split_buyer(chat):
    buy(chat, "t3", "I need 20 cassette AC", "A", "9812340003")
    answer_all(chat, "t4", "I need 20 split AC", {
        "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
        "preferred_brand": "Daikin", "brand_flexible": "yes",
        "city": "Ahmedabad", "area": "Satellite",
        "desired_purchase_date": "Within 7 days", "can_wait": "yes",
        "name": "B", "mobile": "9812340004",
    })
    assert len(groups.list_groups()) == 2, "different products must not pool"
    assert groups.consolidate()["groups_merged"] == 0


def test_a_free_text_answer_does_not_swallow_a_city(chat):
    """The variant slot accepts anything, so it used to eat 'Ahmedabad'."""
    chat("t5", "")
    chat("t5", "I need 20 cassette AC")
    chat("t5", "9812340005")
    reply = chat("t5", "Ahmedabad")          # answering the variant question
    assert reply["summary"]["city"] == "Ahmedabad"
    assert (reply["summary"].get("product") or "").strip().lower() != "cassette ac ahmedabad"
