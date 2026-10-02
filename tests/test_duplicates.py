"""The same person asking for the same thing twice.

Without this the back office sees two buyers where there is one, the customer
gets two sets of notifications about a single order, and the group's buyer
count -- which is what an operator takes to a supplier -- is wrong.
"""
from __future__ import annotations

import pytest

from app.services import groups, intents

from conftest import address_from

MOBILE = "9813100001"

PLY = {
    "thickness": "18 mm", "sheet_size": "8 x 4 ft",
    "preferred_brand": "Century", "brand_flexible": "yes",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 15 days", "can_wait": "yes",
    "name": "Havish",
}


@pytest.fixture(autouse=True)
def plywood_only(monkeypatch):
    import app.catalog as cat

    monkeypatch.setattr(cat, "CATEGORIES", {"PLY": cat.ALL_CATEGORIES["PLY"]})


def order(chat, session, quantity, mobile=MOBILE, duplicate=None, limit=30, **over):
    """Place one order. `duplicate` answers the merge question if it comes."""
    answers = address_from({**PLY, **over})
    asked_duplicate = []
    chat(session, "")
    reply = chat(session, "en")
    for _ in range(limit):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        slot = question["slot"]
        if slot == "_duplicate_choice":
            asked_duplicate.append(reply)
            value = duplicate or "separate"
        elif slot == "_addons":
            value = "__addons_done__"
        elif slot == "_returning_choice":
            value = "new"
        elif slot == "mobile":
            value = mobile
        elif slot == "quantity":
            value = quantity
        else:
            value = answers.get(slot) or (
                question["chips"][0]["value"] if question["chips"] else "skip")
        reply = chat(session, value)
    return reply, asked_duplicate


def ply_intents():
    return intents.list_intents(category="PLY")


# --------------------------------------------------------------------------- #
# when it asks
# --------------------------------------------------------------------------- #
def test_a_first_order_is_never_questioned(chat):
    reply, asked = order(chat, "d1", "100")
    assert reply["done"] is True
    assert not asked, "nothing to be a duplicate of"


def test_the_same_requirement_again_is_offered_a_merge(chat):
    order(chat, "d2a", "100")
    _, asked = order(chat, "d2b", "50", duplicate="separate")

    assert asked, "a repeat of the identical order should be noticed"
    said = " ".join(m.get("text", "") for m in asked[0]["messages"])
    assert "already have an open request" in said
    assert "100 sheets" in said, said
    assert "50 sheets" in said, said
    values = {c["value"] for c in asked[0]["chips"]}
    assert values == {"merge", "separate"}


@pytest.mark.parametrize("difference", [
    {"thickness": "12 mm"},
    {"sheet_size": "6 x 4 ft"},
    {"preferred_brand": "Greenply"},
])
def test_a_different_requirement_is_not_a_duplicate(chat, difference):
    order(chat, "d3a", "100")
    _, asked = order(chat, "d3b", "50", **difference)

    assert not asked, f"{difference} is a different purchase"
    assert len(ply_intents()) == 2


def test_a_different_city_is_not_a_duplicate(chat):
    order(chat, "d4a", "100")
    _, asked = order(chat, "d4b", "50", city="Surat", area="Adajan")

    assert not asked, "same board, different city -- different group entirely"
    assert len(ply_intents()) == 2


def test_another_customer_is_never_a_duplicate(chat):
    """It keys off the number. Two strangers wanting the same board is the
    entire point of the product, not something to merge."""
    order(chat, "d5a", "100")
    _, asked = order(chat, "d5b", "100", mobile="9813100099", name="Ravi")

    assert not asked
    assert len(ply_intents()) == 2
    assert groups.list_groups(category="PLY")[0]["strong_intent_qty"] == 200


# --------------------------------------------------------------------------- #
# merging
# --------------------------------------------------------------------------- #
def test_merging_adds_the_quantity_to_the_one_request(chat):
    order(chat, "d6a", "100")
    reply, asked = order(chat, "d6b", "50", duplicate="merge")

    assert asked and reply["done"] is True
    records = ply_intents()
    assert len(records) == 1, "merging must not leave a second request behind"
    assert records[0]["quantity"] == 150

    group = groups.list_groups(category="PLY")[0]
    assert group["strong_intent_qty"] == 150
    said = " ".join(m.get("text", "") for m in reply["messages"])
    assert "150 sheets" in said, said


def test_merging_shows_the_group_it_landed_in(chat):
    order(chat, "d7a", "100")
    reply, _ = order(chat, "d7b", "50", duplicate="merge")

    cards = [m["card"] for m in reply["messages"] if m.get("card")]
    assert any(c["type"] == "receipt" for c in cards), "no receipt card after merging"
    assert reply["summary"]["group_code"] == groups.list_groups(category="PLY")[0]["code"]


def test_keeping_them_separate_creates_a_second_request(chat):
    order(chat, "d8a", "100")
    reply, asked = order(chat, "d8b", "50", duplicate="separate")

    assert asked and reply["done"] is True
    records = ply_intents()
    assert len(records) == 2
    assert sorted(r["quantity"] for r in records) == [50, 100]
    # Both still pool into the one group -- separate requests, one price.
    assert groups.list_groups(category="PLY")[0]["strong_intent_qty"] == 150


def test_the_question_is_asked_once_not_every_turn(chat):
    """"Keep them separate" must not be re-litigated for the rest of the chat."""
    order(chat, "d9a", "100")
    _, asked = order(chat, "d9b", "50", duplicate="separate")
    assert len(asked) == 1, f"asked {len(asked)} times"


# --------------------------------------------------------------------------- #
# the matching itself
# --------------------------------------------------------------------------- #
def test_duplicate_detection_ignores_quantity_and_companions(chat):
    """Quantity is what gets added together, so it cannot be what separates
    two requirements -- and a companion product is a basket note, not the
    product being bought."""
    order(chat, "d10", "100")
    record = ply_intents()[0]
    state = {
        "category": "PLY", "thickness": "18 mm", "sheet_size": "8 x 4 ft",
        "preferred_brand": "Century", "brand_flexible": "yes",
        "city": "Ahmedabad", "quantity": 999, "addons": ["nails"],
    }
    found = intents.duplicate_for(record["customer_id"], state)
    assert found is not None and found["id"] == record["id"]


def test_a_cancelled_request_is_not_a_duplicate(chat):
    order(chat, "d11a", "100")
    intents.set_status(ply_intents()[0]["id"], "cancelled")

    _, asked = order(chat, "d11b", "50")
    assert not asked, "a cancelled request is not something to add to"
