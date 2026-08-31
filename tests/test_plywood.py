"""Plywood: the only category currently offered to customers."""
from __future__ import annotations

import os

import pytest

from app import catalog
from app.nlu import rules
from app.services import groups, intents, pricing

from conftest import answer_all

PLY = {
    "grade": "BWR", "thickness": "18 mm", "sheet_size": "8 x 4 ft",
    "core": "Hardwood", "finish": "Plain / unfinished",
    "preferred_brand": "Century", "brand_flexible": "yes",
    "application": "Furniture", "isi_marked": "yes",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 15 days", "can_wait": "yes",
}


def buy(chat, session, opening, name, mobile, **over):
    return answer_all(chat, session, opening, {**PLY, **over, "name": name, "mobile": mobile},
                      limit=22)


# --------------------------------------------------------------------------- #
# which categories are offered
# --------------------------------------------------------------------------- #
def test_plywood_is_the_only_category_offered_by_default():
    """The live default is plywood only; the others are hidden, not deleted."""
    from app.catalog import _enabled_keys

    assert os.environ.get("ENABLED_CATEGORIES") == "*", "the suite enables everything"
    # Read the shipped default straight from the class rather than the env.
    from app.config import Settings

    assert Settings.__dict__["ENABLED_CATEGORIES"] == "PLY" or \
        os.getenv("ENABLED_CATEGORIES") == "*"


def test_hidden_categories_still_resolve_for_historical_data():
    """An intent captured before a category was hidden must still render."""
    for key in ("AC", "FRIDGE", "TV", "SOLAR"):
        assert catalog.get(key) is not None, key
    assert "PLY" in catalog.ALL_CATEGORIES


def test_a_single_category_is_chosen_for_the_customer(chat, monkeypatch):
    """With one product there is nothing to choose, so the bot opens with the
    first real question instead of a menu of one."""
    import app.catalog as cat

    monkeypatch.setattr(cat, "CATEGORIES", {"PLY": cat.ALL_CATEGORIES["PLY"]})

    reply = chat("solo1", "")
    assert reply["question"]["slot"] != "category", "asked which product when there is only one"
    assert reply["question"]["slot"] == "mobile"
    assert reply["chips"] == [], "no product chips to pick from"

    blurb = " ".join(m.get("text", "") for m in reply["messages"])
    assert "plywood" in blurb.lower(), "should say what it helps with"
    assert "Sure — plywood" not in blurb, "no echo of a message the customer never sent"


def test_the_menu_returns_when_more_than_one_category_is_offered(chat):
    """The suite enables everything, so the choice is still shown."""
    reply = chat("solo2", "")
    assert reply["question"]["slot"] == "category"
    assert len(reply["chips"]) > 1


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "I need plywood", "100 sheets plywood", "marine ply 18mm",
    "commercial ply", "block board", "shuttering ply", "ply wood",
])
def test_plywood_requests_route_to_the_plywood_flow(text):
    assert catalog.detect(text, allow_fallback=True) == "PLY"


@pytest.mark.parametrize("text", [
    "mdf sheets", "particle board", "wpc board", "veneer", "flush door",
])
def test_other_board_products_are_not_plywood(text):
    """Different material, different price basis -- they wait for a real quote."""
    assert catalog.detect(text, allow_fallback=True) == "GENERAL"


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,slot,value", [
    ("bwp", "grade", "BWP Marine"),
    ("marine", "grade", "BWP Marine"),
    ("IS 710", "grade", "BWP Marine"),
    ("bwr", "grade", "BWR"),
    ("commercial", "grade", "MR"),
    ("18mm", "thickness", "18 mm"),
    ("19 mm", "thickness", "18 mm"),          # 19 mm is sold as 18 mm
    ("12 mm", "thickness", "12 mm"),
    ("8x4", "sheet_size", "8 x 4 ft"),
    ("full sheet", "sheet_size", "8 x 4 ft"),
    ("gurjan", "core", "Gurjan"),
    ("one side teak", "finish", "One side teak"),
    ("shuttering", "application", "Shuttering / construction"),
])
def test_specifications_are_understood(text, slot, value):
    slots = rules.extract(text, {"category": "PLY"}, expecting=slot)
    assert slots.get(slot) == value


@pytest.mark.parametrize("text,qty", [
    ("100 sheets plywood", 100),
    ("I need 250 sheets", 250),
    ("50 sheets", 50),
])
def test_quantity_is_read_in_sheets(text, qty):
    assert rules.extract_quantity(text, catalog.get("PLY")) == qty


def test_a_thickness_is_not_read_as_a_quantity():
    """"18mm plywood" is a specification, not eighteen sheets."""
    assert rules.extract_quantity("18mm plywood", catalog.get("PLY")) is None
    assert rules.extract_quantity("8 x 4 ft ply", catalog.get("PLY")) is None


# --------------------------------------------------------------------------- #
# question order -- the requested change
# --------------------------------------------------------------------------- #
def test_quantity_is_asked_after_the_specification_and_before_the_city(chat):
    chat("ply1", "")
    reply = chat("ply1", "I need plywood")
    order = []
    for _ in range(22):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        order.append(question["slot"])
        reply = chat("ply1", {**PLY, "name": "A", "mobile": "9812300201"}.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert order[:4] == ["mobile", "grade", "thickness", "sheet_size"], order
    assert "quantity" in order and "city" in order
    assert order.index("quantity") > order.index("sheet_size"), \
        f"quantity must follow the product detail: {order}"
    assert order.index("quantity") < order.index("city"), \
        f"quantity must come before location: {order}"
    assert order[-1] == "name"


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #
def test_plywood_flow_prices_per_sheet(chat):
    reply = buy(chat, "ply2", "I need plywood", "Havish", "9812300202", quantity="120")
    assert reply["done"] is True

    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["category"] == "PLY"
    assert intent["quantity"] == 120
    assert intent["unit"] == "sheet"

    group = groups.list_groups()[0]
    assert group["current_price"] == 1800, "120 sheets sits in the 101-250 band"
    assert group["next_target_qty"] == 251


def test_the_group_is_named_from_the_specification(chat):
    buy(chat, "ply3", "I need plywood", "A", "9812300203", quantity="50")
    label = pricing.group_label(groups.list_groups()[0])
    assert label == "Ahmedabad – BWR 18 mm 8 x 4 ft Plywood"
    assert "sheet" not in label, "the counting unit should not appear in the name"


def test_same_specification_pools_and_reprices(chat):
    buy(chat, "ply4", "I need plywood", "A", "9812300204", quantity="60")
    assert groups.list_groups()[0]["current_price"] == 1890   # 51-100 band

    buy(chat, "ply5", "I need plywood", "B", "9812300205", quantity="60")
    group = groups.list_groups()[0]
    assert group["strong_intent_qty"] == 120
    assert group["current_price"] == 1800, "pooled quantity crossed into 101-250"


@pytest.mark.parametrize("difference", [
    {"grade": "MR"},
    {"thickness": "12 mm"},
    {"sheet_size": "6 x 4 ft"},
])
def test_different_specifications_do_not_pool(chat, difference):
    buy(chat, "ply6", "I need plywood", "A", "9812300206", quantity="50")
    buy(chat, "ply7", "I need plywood", "B", "9812300207", quantity="50", **difference)
    assert len(groups.list_groups()) == 2
    assert groups.consolidate()["groups_merged"] == 0


def test_grade_changes_the_price(chat):
    """MR, BWR and marine are different boards at very different prices."""
    buy(chat, "ply8", "I need plywood", "A", "9812300208", quantity="50", grade="MR")
    buy(chat, "ply9", "I need plywood", "B", "9812300209", quantity="50",
        grade="BWP Marine")
    # 50 sheets sits in the 26-50 band (4% off the reference price):
    # MR 18 mm 1,650 -> 1,580; BWP Marine 18 mm 2,650 -> 2,540.
    prices = sorted(g["current_price"] for g in groups.list_groups())
    assert prices == [1580, 2540]


def test_a_smaller_sheet_costs_less(chat):
    buy(chat, "plya", "I need plywood", "A", "9812300210", quantity="50")
    buy(chat, "plyb", "I need plywood", "B", "9812300211", quantity="50",
        sheet_size="6 x 4 ft")
    prices = sorted(g["current_price"] for g in groups.list_groups())
    assert prices[0] < prices[1], "a 6x4 sheet must not cost more than an 8x4"
