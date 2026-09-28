"""A companion product is a purchase in its own right.

Picking "nails" is not a requirement anyone can quote. So each companion
product asks the two or three things that decide its price, and the answers
become an intent with its own group -- pooling with every other buyer who needs
the same nails in the same city.
"""
from __future__ import annotations

import pytest

from app import catalog
from app.catalog import supplies
from app.db import loads
from app.services import groups, intents

PLY = {
    "grade": "BWR", "thickness": "18 mm", "sheet_size": "8 x 4 ft",
    "core": "Hardwood", "finish": "Plain / unfinished",
    "preferred_brand": "Century", "brand_flexible": "yes",
    "application": "Furniture", "isi_marked": "yes", "quantity": "120",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 15 days", "can_wait": "yes",
}

DONE = "__addons_done__"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def drive_to_addons(chat, session, name, mobile, **over):
    answers = {**PLY, **over, "name": name, "mobile": mobile}
    chat(session, "")
    reply = chat(session, "I need plywood")
    for _ in range(24):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        if question["slot"] == "_addons":
            return reply
        reply = chat(session, answers.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))
    raise AssertionError("never reached the companion-product step")


def answer_companions(chat, session, reply, answers=None, limit=24):
    """Answer every `_ax:` question, recording the slots asked."""
    answers = answers or {}
    asked = []
    for _ in range(limit):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        slot = question["slot"]
        assert slot.startswith("_ax:"), f"unexpected question {slot}"
        asked.append(slot[len("_ax:"):])
        value = answers.get(asked[-1])
        if value is None:
            value = question["chips"][0]["value"] if question["chips"] else "skip"
        reply = chat(session, value)
    return reply, asked


def buy_plywood_with(chat, session, name, mobile, picks, answers=None):
    """The whole journey: plywood, then each companion product specified."""
    drive_to_addons(chat, session, name, mobile)
    for key in picks:
        chat(session, f"addon:{key}")
    reply = chat(session, DONE)
    return answer_companions(chat, session, reply, answers)


def spec_of(intent_id):
    return loads(intents.get(intent_id)["specifications_json"], {})


def group_for(category_key):
    found = groups.list_groups(category=category_key)
    assert found, f"no {category_key} group was created"
    return found[0]


def only_member(category_key):
    """The single intent in that category's group."""
    found = groups.members(group_for(category_key)["id"])
    assert len(found) == 1, found
    return found[0]


# --------------------------------------------------------------------------- #
# the catalogue
# --------------------------------------------------------------------------- #
def test_every_companion_product_is_a_real_category():
    for addon in catalog.get("PLY").addons:
        product = catalog.get(addon.category_key)
        assert product is not None, addon.key
        assert product.addon_only, f"{product.key} must not appear in the opening menu"
        assert len(product.grouping_fields) >= 1, product.key
        # Every grouping field is something the flow actually asks about.
        names = {s.name for s in product.slots}
        assert set(product.grouping_fields) <= names, product.key


def test_companion_products_are_never_offered_in_the_opening_menu(chat):
    """They are reached by picking them alongside an order, not chosen first."""
    offered = {c.key for c in catalog.all_categories()}
    for key in supplies.KEYS:
        assert key not in offered, key
        assert key in catalog.ALL_CATEGORIES, f"{key} must still resolve for the back office"


def test_companion_products_start_with_no_price():
    """Nobody has quoted for them, so no slab may be invented."""
    for key in supplies.KEYS:
        assert catalog.get(key).slabs == {}, key


# --------------------------------------------------------------------------- #
# the questions
# --------------------------------------------------------------------------- #
def test_nails_are_asked_for_size_type_and_quantity(chat):
    """The brief's example: "for Nail ask size and all"."""
    reply, asked = buy_plywood_with(chat, "s1", "Havish", "9812360001", ["nails"])

    assert asked[:2] == ["nail_size", "nail_type"], asked
    assert "quantity" in asked, asked
    assert reply["done"] is True


def test_the_specification_is_asked_before_the_quantity(chat):
    """"How many kg of nails?" means nothing until we know which nails."""
    _, asked = buy_plywood_with(chat, "s2", "Havish", "9812360002", ["nails"])
    assert asked.index("quantity") > asked.index("nail_type"), asked


def test_what_we_already_know_is_not_asked_again(chat):
    """Same buyer, same city, same deadline -- only the product is new."""
    _, asked = buy_plywood_with(chat, "s3", "Havish", "9812360003", ["adhesive"])
    for known in ("city", "area", "name", "mobile", "desired_purchase_date", "can_wait"):
        assert known not in asked, f"re-asked {known}: {asked}"


def test_each_pick_gets_its_own_questions(chat):
    _, asked = buy_plywood_with(chat, "s4", "Havish", "9812360004",
                                ["adhesive", "nails"])
    assert {"adhesive_type", "pack_size"} <= set(asked), asked
    assert {"nail_size", "nail_type"} <= set(asked), asked


@pytest.mark.parametrize("text,slot,value", [
    ("2 inch", "nail_size", "2 inch"),
    ('1.5"', "nail_size", "1.5 inch"),
    ("50 mm", "nail_size", "2 inch"),
    ("panel pins", "nail_type", "Panel pin"),
    ("for nail gun", "nail_type", "Brad"),
    ("galvanised", "nail_finish", "Galvanised"),
])
def test_nail_answers_are_understood(text, slot, value):
    from app.nlu import rules

    assert rules.extract(text, {"category": "NAILS"}, expecting=slot).get(slot) == value


@pytest.mark.parametrize("text,slot,value", [
    ("fevicol sh", "adhesive_type", "White glue"),
    ("sr 998", "adhesive_type", "Rubber-based"),
    ("marine", "adhesive_type", "Synthetic resin"),
    ("20 kg bucket", "pack_size", "20 kg"),
    ("half kg", "pack_size", "500 g"),
])
def test_adhesive_answers_are_understood(text, slot, value):
    from app.nlu import rules

    assert rules.extract(text, {"category": "ADHESIVE"}, expecting=slot).get(slot) == value


def test_a_typed_quantity_is_read_in_the_right_unit(chat):
    """Nails are bought by weight, not by the piece."""
    reply, _ = buy_plywood_with(chat, "s5", "Havish", "9812360005", ["nails"],
                                answers={"quantity": "5 kg"})
    assert reply["done"] is True

    record = only_member("NAILS")
    assert record["quantity"] == 5
    assert record["unit"] == "kg"


# --------------------------------------------------------------------------- #
# what it is all for: a group of its own
# --------------------------------------------------------------------------- #
def test_the_companion_product_becomes_its_own_group(chat):
    buy_plywood_with(chat, "s6", "Havish", "9812360006", ["nails"],
                     answers={"nail_size": "2 inch", "nail_type": "Wire", "quantity": "10"})

    group = group_for("NAILS")
    assert group["code"].startswith("NAILS-AHM-")
    assert group["city"] == "Ahmedabad"
    assert group["strong_intent_qty"] == 10
    assert groups.spec_of(group)["nail_size"] == "2 inch"


def test_matching_companion_requirements_pool_together(chat):
    """The whole point: two plywood buyers wanting the same nails are one order."""
    for n, (name, mobile) in enumerate([("A", "9812360011"), ("B", "9812360012")]):
        buy_plywood_with(chat, f"s7{n}", name, mobile, ["nails"],
                         answers={"nail_size": "2 inch", "nail_type": "Wire",
                                  "quantity": "10"})

    nail_groups = groups.list_groups(category="NAILS")
    assert len(nail_groups) == 1, "same nails, same city -- one group"
    assert nail_groups[0]["strong_intent_qty"] == 20


def test_different_companion_specifications_do_not_pool(chat):
    buy_plywood_with(chat, "s8a", "A", "9812360021", ["nails"],
                     answers={"nail_size": "2 inch", "nail_type": "Wire", "quantity": "10"})
    buy_plywood_with(chat, "s8b", "B", "9812360022", ["nails"],
                     answers={"nail_size": "4 inch", "nail_type": "Concrete", "quantity": "10"})

    assert len(groups.list_groups(category="NAILS")) == 2
    assert groups.consolidate()["groups_merged"] == 0


def test_the_companion_group_quotes_no_price(chat):
    """No supplier has quoted for nails, so the bot must not imply a number."""
    reply, _ = buy_plywood_with(chat, "s9", "Havish", "9812360009", ["nails"])

    group = group_for("NAILS")
    assert group["current_price"] in (None, 0)

    said = " ".join(m.get("text", "") for m in reply["messages"])
    assert "₹" not in said, said


def test_the_main_order_is_banked_before_the_questions_start(chat):
    """Whatever happens next, the thing they came for is already recorded."""
    drive_to_addons(chat, "s10", "Havish", "9812360010")
    chat("s10", "addon:nails")
    reply = chat("s10", DONE)

    assert reply["done"] is False, "the companion questions still have to be asked"
    assert reply["summary"]["intent_id"] is not None
    assert groups.list_groups(category="PLY"), "the plywood group exists already"
    assert intents.get(reply["summary"]["intent_id"])["status"] == "active"


def test_the_sign_off_waits_until_everything_is_captured(chat):
    """"You're done" belongs at the end, not in the middle."""
    drive_to_addons(chat, "s11", "Havish", "9812360013")
    chat("s11", "addon:nails")
    mid = chat("s11", DONE)
    assert not [m for m in mid["messages"] if m.get("card", {}).get("type") == "done"]

    end, _ = answer_companions(chat, "s11", mid)
    assert [m for m in end["messages"] if m.get("card", {}).get("type") == "done"]
    assert end["done"] is True


def test_cancelling_takes_the_companion_requirement_with_it(chat):
    """Cancelling the board and leaving the glue behind would be a trap."""
    reply, _ = buy_plywood_with(chat, "s12", "Havish", "9812360014", ["nails"])
    main = reply["summary"]["intent_id"]
    nails = only_member("NAILS")["id"]

    chat("s12", "cancel my request")
    assert intents.get(main)["status"] == "cancelled"
    assert intents.get(nails)["status"] == "cancelled"


# --------------------------------------------------------------------------- #
# the back office
# --------------------------------------------------------------------------- #
def test_the_bundle_shows_the_real_pooled_quantity(chat):
    for n, mobile in enumerate(["9812360031", "9812360032"]):
        buy_plywood_with(chat, f"s13{n}", f"Buyer{n}", mobile, ["nails"],
                         answers={"nail_size": "2 inch", "nail_type": "Wire",
                                  "quantity": "10"})

    ply = groups.list_groups(category="PLY")[0]
    row = next(r for r in groups.addon_demand(ply["id"]) if r["key"] == "nails")

    assert row["buyers"] == 2
    assert row["specified"] == 2
    assert row["quantity"] == 20
    assert row["quantity_text"] == "20 kg"
    assert row["groups"] == [group_for("NAILS")["code"]]


def test_no_quantity_is_claimed_before_the_buyer_gives_one(chat):
    """A pick on its own is a head count, nothing more."""
    drive_to_addons(chat, "s14", "Havish", "9812360015")
    chat("s14", "addon:nails")
    chat("s14", DONE)          # the nail questions are asked but not answered

    ply = groups.list_groups(category="PLY")[0]
    row = next(r for r in groups.addon_demand(ply["id"]) if r["key"] == "nails")
    assert row["buyers"] == 1
    assert "quantity" not in row


def test_the_bundle_reaches_the_back_office(chat, client):
    """The admin group page reads this straight off the API."""
    buy_plywood_with(chat, "s16", "Havish", "9812360017", ["nails"],
                     answers={"quantity": "10"})

    ply = groups.list_groups(category="PLY")[0]
    payload = client.get(f"/api/admin/groups/{ply['code']}").json()
    row = next(r for r in payload["addon_demand"] if r["key"] == "nails")
    assert row["quantity_text"] == "10 kg"
    assert row["groups"] == [group_for("NAILS")["code"]]


def test_the_companion_intent_points_back_at_the_order(chat):
    reply, _ = buy_plywood_with(chat, "s15", "Havish", "9812360016", ["nails"])
    ply_code = reply["summary"]["group_code"]

    nails = only_member("NAILS")["id"]
    assert spec_of(nails)["for_group"] == ply_code
