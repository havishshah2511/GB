"""Automatic group consolidation.

A background pass pools any two open groups buying the same product in the same
city, so a split can never survive -- whatever caused it.
"""
from __future__ import annotations

from datetime import timedelta

from app.db import today
from app.services import groups, intents, matching, notifications, pricing
from app.worker import run_once

from conftest import answer_all

FRIDGE = {
    "capacity": "200-300 L", "door_type": "Double Door", "defrost": "Frost Free",
    "city": "Vadodara", "area": "Alkapuri", "preferred_brand": "LG",
    "brand_flexible": "yes", "star_rating": "3 Star", "usage": "Home",
    "can_wait": "yes", "desired_purchase_date": "Within 7 days",
}


def fridge_buyer(chat, session, opening, name, mobile, **overrides):
    return answer_all(chat, session, opening,
                      {**FRIDGE, **overrides, "name": name, "mobile": mobile})


def force_split(chat):
    """Create the reported situation: two open groups, same product, same city.

    Built by moving the second buyer into a group of their own, the way the old
    matching rules used to.
    """
    fridge_buyer(chat, "c1", "I need 3 fridge", "Havish", "9000000001")
    fridge_buyer(chat, "c2", "I need 4 fridge", "Harsh", "9000000002")

    first, second = intents.list_intents()[::-1]
    original = groups.get(first["group_id"])
    groups.split(original["id"], [second["id"]])
    assert len(groups.list_groups()) == 2, "test setup failed to split"
    return original


# --------------------------------------------------------------------------- #
def test_consolidate_pools_two_groups_for_the_same_product(chat):
    force_split(chat)

    outcome = groups.consolidate()
    assert outcome["groups_merged"] == 1

    open_groups = groups.list_groups()
    assert len(open_groups) == 1
    assert open_groups[0]["strong_intent_qty"] == 7


def test_consolidation_repriced_the_pooled_group(chat):
    force_split(chat)
    groups.consolidate()

    group = groups.list_groups()[0]
    assert group["current_price"] == 30800, "7 units should sit in the 6-10 slab"
    assert group["next_target_qty"] == 11


def test_the_larger_group_absorbs_the_smaller(chat):
    """Codes already shared with customers should keep working where possible."""
    force_split(chat)
    before = {g["code"]: g["strong_intent_qty"] for g in groups.list_groups()}
    biggest = max(before, key=before.get)

    groups.consolidate()
    assert groups.list_groups()[0]["code"] == biggest


def test_dry_run_reports_without_changing_anything(chat):
    force_split(chat)

    preview = groups.consolidate(dry_run=True)
    assert preview["groups_merged"] == 1
    assert preview["dry_run"] is True
    assert len(groups.list_groups()) == 2, "dry run must not merge"


def test_the_background_worker_consolidates(chat):
    force_split(chat)
    result = run_once()
    assert result["groups_merged"] == 1
    assert len(groups.list_groups()) == 1


def test_members_of_the_absorbed_group_are_told_about_the_new_price(chat):
    """The absorbed buyer's price improves, but the target group's own price
    may not move at all -- so recalculate() can never discover this."""
    force_split(chat)

    # Havish is alone in the 3-unit group paying ₹32,000; the other is at ₹30,800.
    small = min(groups.list_groups(), key=lambda g: g["strong_intent_qty"])
    havish = groups.members(small["id"], active_only=True)[0]
    assert small["current_price"] == 32000

    before = len(notifications.history(customer_id=havish["customer_id"]))
    groups.consolidate()
    after = notifications.history(customer_id=havish["customer_id"])

    assert len(after) > before, "the absorbed buyer was never told"
    drop = next(n for n in after if n["type"] == "price_drop")
    assert "₹30,800" in drop["message"]
    assert "₹32,000" in drop["message"], "should show what they were paying before"


def test_consolidation_is_idempotent(chat):
    force_split(chat)
    assert groups.consolidate()["groups_merged"] == 1
    assert groups.consolidate()["groups_merged"] == 0
    assert len(groups.list_groups()) == 1


# --------------------------------------------------------------------------- #
# what must NOT be pooled
# --------------------------------------------------------------------------- #
def test_different_cities_are_left_alone(chat):
    fridge_buyer(chat, "d1", "I need 5 fridge", "A", "9000001001")
    fridge_buyer(chat, "d2", "I need 5 fridge", "B", "9000001002",
               city="Surat", area="Adajan")

    assert groups.consolidate()["groups_merged"] == 0
    assert len(groups.list_groups()) == 2


def test_different_specifications_are_left_alone(chat):
    fridge_buyer(chat, "d3", "I need 5 fridge", "A", "9000001003")
    fridge_buyer(chat, "d4", "I need 5 fridge", "B", "9000001004",
               capacity="500 L+", door_type="Side-by-Side")

    assert groups.consolidate()["groups_merged"] == 0
    assert len(groups.list_groups()) == 2


def test_a_brand_locked_group_is_never_pooled_with_a_flexible_one(chat):
    fridge_buyer(chat, "d5", "I need 5 fridge", "A", "9000001005")
    fridge_buyer(chat, "d6", "I need 5 fridge", "B", "9000001006",
               brand_flexible="no")

    modes = sorted(g["match_mode"] for g in groups.list_groups())
    assert modes == ["exact", "flexible"]
    assert groups.consolidate()["groups_merged"] == 0, (
        "a buyer who insists on one brand must not be pooled into a group "
        "that may buy any brand"
    )


def test_groups_with_unrelated_purchase_windows_are_left_alone(chat):
    fridge_buyer(chat, "d7", "I need 5 fridge", "A", "9000001007")
    far = str(today() + timedelta(days=150))
    fridge_buyer(chat, "d8", "I need 5 fridge", "B", "9000001008",
               desired_purchase_date=far)

    assert len(groups.list_groups()) == 2
    assert groups.consolidate()["groups_merged"] == 0


def test_mergeable_explains_its_refusals(chat):
    fridge_buyer(chat, "d9", "I need 5 fridge", "A", "9000001009")
    fridge_buyer(chat, "d10", "I need 5 fridge", "B", "9000001010",
               city="Surat", area="Adajan")

    a, b = groups.list_groups()
    ok, reason = groups.mergeable(a, b)
    assert ok is False
    assert "city" in reason


# --------------------------------------------------------------------------- #
def test_admin_can_preview_and_run_consolidation(client, chat):
    force_split(chat)

    preview = client.post("/api/admin/groups/consolidate?dry_run=true").json()
    assert preview["groups_merged"] == 1
    assert len(groups.list_groups()) == 2

    done = client.post("/api/admin/groups/consolidate").json()
    assert done["groups_merged"] == 1
    assert done["merged"][0]["reason"]
    assert len(groups.list_groups()) == 1
