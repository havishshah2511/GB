"""Companion products offered alongside the main order.

Someone buying plywood almost always needs adhesive and hardware in the same
week. Capturing that turns one line item into a basket the operator can
negotiate as a bundle.
"""
from __future__ import annotations

import pytest

from app import catalog
from app.db import loads
from app.services import groups, intents

from conftest import answer_all

PLY = {
    "grade": "BWR", "thickness": "18 mm", "sheet_size": "8 x 4 ft",
    "core": "Hardwood", "finish": "Plain / unfinished",
    "preferred_brand": "Century", "brand_flexible": "yes",
    "application": "Furniture", "isi_marked": "yes", "quantity": "120",
    "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 15 days", "can_wait": "yes",
}

DONE = "__addons_done__"


def drive_to_addons(chat, session, name, mobile):
    """Answer everything up to the companion-product step."""
    answers = {**PLY, "name": name, "mobile": mobile}
    chat(session, "")
    reply = chat(session, "I need plywood")
    for _ in range(22):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        if question["slot"] == "_addons":
            return reply
        reply = chat(session, answers.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))
    raise AssertionError("never reached the companion-product step")


def cards(reply, kind):
    return [m["card"] for m in reply["messages"] if m.get("card", {}).get("type") == kind]


def spec_of(intent_id):
    return loads(intents.get(intent_id)["specifications_json"], {})


# --------------------------------------------------------------------------- #
# the offer
# --------------------------------------------------------------------------- #
def test_companion_products_are_offered_after_the_requirement(chat):
    reply = drive_to_addons(chat, "a1", "Havish", "9812340001")

    labels = [c["label"] for c in reply["chips"]]
    assert any("Adhesive" in l for l in labels), labels
    assert any("Nails" in l for l in labels)
    assert any("No thanks" in l for l in labels)

    # Each one says what it means, by the name the trade uses. "Adhesive" on
    # its own tells a buyer nothing.
    hints = " ".join(c.get("hint", "") for c in reply["chips"])
    assert "Fevicol" in hints, hints
    assert "panel pins" in hints

    blurb = " ".join(m.get("text", "") for m in reply["messages"])
    assert "plywood" in blurb.lower()


def test_the_offer_comes_last_not_first(chat):
    """It should read as a helpful nudge, not an upsell before we listened."""
    chat("a2", "")
    reply = chat("a2", "I need plywood")
    order = []
    for _ in range(22):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        order.append(question["slot"])
        if question["slot"] == "_addons":
            break
        reply = chat("a2", {**PLY, "name": "A", "mobile": "9812340002"}.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert order[-1] == "_addons"
    for earlier in ("grade", "thickness", "quantity", "city", "name"):
        assert earlier in order and order.index(earlier) < order.index("_addons")


def test_picking_several_accumulates(chat):
    drive_to_addons(chat, "a3", "Havish", "9812340003")
    reply = chat("a3", "addon:adhesive")
    assert "Adhesive" in " ".join(m.get("text", "") for m in reply["messages"])

    reply = chat("a3", "addon:nails")
    blurb = " ".join(m.get("text", "") for m in reply["messages"])
    assert "Adhesive" in blurb and "Nails" in blurb

    # A chosen item is not offered again.
    labels = [c["label"] for c in reply["chips"]]
    assert not any("Adhesive" in l for l in labels)
    assert any("everything" in l.lower() for l in labels)


def test_choices_are_saved_on_the_intent(chat):
    drive_to_addons(chat, "a4", "Havish", "9812340004")
    chat("a4", "addon:adhesive")
    chat("a4", "addon:nails")
    reply = chat("a4", DONE)

    # The main order is banked as soon as the picks are in; each pick then gets
    # its own questions (tests/test_addon_specs.py).
    assert spec_of(reply["summary"]["intent_id"])["addons"] == ["adhesive", "nails"]

    listed = cards(reply, "addons")
    assert listed and listed[0]["items"] == ["Adhesive", "Nails & pins"]


def test_the_confirmation_promises_no_price(chat):
    """Nobody has quoted for these, so no number may appear."""
    drive_to_addons(chat, "a5", "Havish", "9812340005")
    chat("a5", "addon:adhesive")
    reply = chat("a5", DONE)

    card = cards(reply, "addons")[0]
    assert "₹" not in card["note"]
    assert "quote" in card["note"].lower()


@pytest.mark.parametrize("typed,expected", [
    ("fevicol", ["adhesive"]),
    ("glue and nails", ["adhesive", "nails"]),
    ("sunmica", ["laminate"]),
    ("kabza", ["hardware"]),
])
def test_typed_answers_are_understood(chat, typed, expected):
    session = f"a6-{typed[:4]}"
    drive_to_addons(chat, session, "Havish", f"981234{abs(hash(typed)) % 10000:04d}")
    chat(session, typed)
    reply = chat(session, DONE)
    assert spec_of(reply["summary"]["intent_id"])["addons"] == expected


def test_declining_leaves_a_clean_intent(chat):
    drive_to_addons(chat, "a7", "Havish", "9812340007")
    reply = chat("a7", DONE)

    assert reply["done"] is True
    assert "addons" not in spec_of(reply["summary"]["intent_id"])
    assert not cards(reply, "addons"), "nothing to confirm when nothing was picked"


@pytest.mark.parametrize("phrase", ["no thanks", "no", "nothing", "bas", "that's all", "nahi"])
def test_declining_in_words_does_not_end_the_chat(chat, phrase):
    """These phrases normally mean "exit". At this step they mean "no add-ons",
    and treating them as exit would throw away the whole requirement."""
    session = f"a8-{phrase[:3]}"
    drive_to_addons(chat, session, "Havish", f"98123410{abs(hash(phrase)) % 100:02d}")
    reply = chat(session, phrase)

    assert reply["done"] is True
    assert reply["summary"]["intent_id"] is not None, "the requirement was lost"
    assert "addons" not in spec_of(reply["summary"]["intent_id"])


def test_cancelling_still_works_at_this_step(chat):
    """A real command must still get through."""
    drive_to_addons(chat, "a9", "Havish", "9812341999")
    reply = chat("a9", "cancel my request")

    blurb = " ".join(m.get("text", "") for m in reply["messages"]).lower()
    assert "cancel" in blurb or "nothing to cancel" in blurb
    assert reply["summary"]["intent_id"] is None


# --------------------------------------------------------------------------- #
# what it is for: the bundle an operator negotiates
# --------------------------------------------------------------------------- #
def test_the_back_office_sees_pooled_addon_demand(chat):
    for n, picks in enumerate([("adhesive", "nails"), ("adhesive",), ("adhesive", "screws")]):
        session = f"b{n}"
        drive_to_addons(chat, session, f"Buyer{n}", f"981235000{n}")
        for key in picks:
            chat(session, f"addon:{key}")
        chat(session, DONE)

    group = groups.list_groups(category="PLY")[0]
    demand = {row["label"]: row["buyers"] for row in groups.addon_demand(group["id"])}
    assert demand["Adhesive"] == 3, demand
    assert demand["Nails & pins"] == 1
    assert demand["Screws"] == 1
    assert "Hinges & fittings" not in demand, "nothing nobody asked for"


def test_addon_demand_is_buyer_counts_not_invented_quantities(chat):
    drive_to_addons(chat, "b9", "Havish", "9812350009")
    chat("b9", "addon:adhesive")
    chat("b9", DONE)          # the adhesive questions are asked, not answered

    row = groups.addon_demand(groups.list_groups(category="PLY")[0]["id"])[0]
    assert row["buyers"] == 1
    # This buyer has not said how much glue they need, so no quantity is
    # claimed. It appears only once they answer -- see test_addon_specs.py.
    assert "quantity" not in row and "qty" not in row


def test_a_category_without_addons_skips_the_step(chat):
    """AC declares none, so its flow must be unchanged."""
    assert not catalog.get("AC").addons
    reply = answer_all(chat, "b10", "I need 2 AC", {
        "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
        "preferred_brand": "Daikin", "brand_flexible": "yes", "star_rating": "5 Star",
        "city": "Ahmedabad", "area": "Satellite",
        "desired_purchase_date": "Within 7 days", "can_wait": "yes",
        "name": "Rahul", "mobile": "9812350010",
    })
    assert reply["done"] is True
    assert not cards(reply, "addons")
