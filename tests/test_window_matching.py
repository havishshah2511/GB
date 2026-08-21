"""Purchase-window semantics.

Reported bug: two buyers wanting the same product in the same city landed in
separate groups because one said "within 7 days" and the other "within 15
days". Their windows were computed as 24-31 Aug and 1-8 Sep -- adjacent,
non-overlapping -- so the matcher rejected the group, the quantities never
combined, the price never dropped and nobody was notified.

(It was first reported against rice, which has since been replaced by the
refrigerator category; the scenario is category-agnostic.)

"Within N days" is a deadline, not an appointment: the buyer is available from
today until then.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import parse_date, today
from app.services import groups, intents, matching, notifications

from conftest import answer_all

FRIDGE = {
    "capacity": "200-300 L", "door_type": "Double Door", "defrost": "Frost Free",
    "city": "Vadodara", "area": "Alkapuri", "preferred_brand": "LG",
    "brand_flexible": "yes", "star_rating": "3 Star", "usage": "Home",
    "can_wait": "yes",
}


def fridge_buyer(chat, session, opening, when, name, mobile):
    return answer_all(chat, session, opening, {
        **FRIDGE, "desired_purchase_date": when, "name": name, "mobile": mobile,
    })


# --------------------------------------------------------------------------- #
# the reported failure
# --------------------------------------------------------------------------- #
def test_different_deadlines_still_share_one_group(chat):
    fridge_buyer(chat, "w1", "I need 3 fridge", "Within 7 days",
               "Havish", "9000000001")
    fridge_buyer(chat, "w2", "I need 4 fridge", "Within 15 days",
               "Harsh", "9000000002")

    all_groups = groups.list_groups()
    assert len(all_groups) == 1, (
        "same product, same city, overlapping deadlines must pool into one group; "
        f"got {[g['code'] for g in all_groups]}"
    )
    assert all_groups[0]["strong_intent_qty"] == 7


def test_pooling_drops_the_price_and_notifies_the_earlier_buyer(chat):
    fridge_buyer(chat, "w3", "I need 3 fridge", "Within 7 days",
               "Havish", "9000000003")
    before = groups.list_groups()[0]
    assert before["current_price"] == 32000

    fridge_buyer(chat, "w4", "I need 4 fridge", "Within 15 days",
               "Harsh", "9000000004")
    after = groups.get(before["id"])
    assert after["current_price"] == 30800, "combined quantity did not reprice the group"

    drops = [
        n for n in notifications.history(group_id=after["id"])
        if n["type"] == "price_drop"
    ]
    assert [n["customer_mobile"] for n in drops] == ["9000000003"], (
        "the earlier buyer must hear about it; the buyer who caused it must not"
    )
    assert "₹30,800" in drops[0]["message"]


@pytest.mark.parametrize("first,second", [
    ("Immediately", "Within 30 days"),
    ("Within 3 days", "Within 15 days"),
    ("Within 7 days", "Within 15 days"),
    ("Within 15 days", "Within 7 days"),
    ("Within 15 days", "Within 30 days"),
])
def test_any_pair_of_deadlines_pools(chat, first, second):
    fridge_buyer(chat, "p1", "I need 4 fridge", first, "A", "9000001001")
    fridge_buyer(chat, "p2", "I need 4 fridge", second, "B", "9000001002")
    assert len(groups.list_groups()) == 1, f"{first} + {second} split the group"


# --------------------------------------------------------------------------- #
# the window itself
# --------------------------------------------------------------------------- #
def test_a_deadline_answer_makes_the_buyer_available_from_today(chat):
    fridge_buyer(chat, "w5", "I need 5 fridge", "Within 15 days",
               "Chetan", "9000000005")
    intent = intents.list_intents()[0]

    assert parse_date(intent["earliest_purchase_date"]) == today()
    assert parse_date(intent["desired_purchase_date"]) == today() + timedelta(days=15)

    start, end = matching._window(intent)
    assert start == today()
    assert end >= parse_date(intent["desired_purchase_date"])


def test_an_explicit_date_is_respected_as_the_earliest(chat):
    """Someone naming a calendar date means 'not before then'."""
    target = str(today() + timedelta(days=40))
    fridge_buyer(chat, "w6", "I need 5 fridge", target, "Deepa", "9000000006")
    intent = intents.list_intents()[0]

    assert parse_date(intent["desired_purchase_date"]) == parse_date(target)
    start, _ = matching._window(intent)
    assert start == parse_date(target), "an explicit date must not be moved to today"


def test_group_window_spans_from_the_earliest_member_date(chat):
    fridge_buyer(chat, "w7", "I need 4 fridge", "Within 7 days",
               "Esha", "9000000007")
    fridge_buyer(chat, "w8", "I need 4 fridge", "Within 30 days",
               "Farhan", "9000000008")

    group = groups.list_groups()[0]
    assert parse_date(group["purchase_window_start"]) == today()
    assert parse_date(group["purchase_window_end"]) >= today() + timedelta(days=30)


def test_a_far_future_buyer_does_not_join_an_urgent_group(chat):
    """Windows still discriminate: someone buying in four months should not be
    pooled with a group closing this week."""
    fridge_buyer(chat, "w9", "I need 4 fridge", "Within 3 days",
               "Gita", "9000000009")
    far = str(today() + timedelta(days=120))
    fridge_buyer(chat, "w10", "I need 4 fridge", far, "Hemant", "9000000010")

    assert len(groups.list_groups()) == 2, "unrelated purchase windows must not merge"


# --------------------------------------------------------------------------- #
# brand locking is a separate, intended reason to split
# --------------------------------------------------------------------------- #
def test_a_brand_locked_buyer_still_gets_their_own_group(chat):
    answer_all(chat, "b1", "I need 4 fridge", {
        **FRIDGE, "desired_purchase_date": "Within 7 days",
        "name": "Ira", "mobile": "9000002001",
    })
    answer_all(chat, "b2", "I need 4 fridge", {
        **FRIDGE, "brand_flexible": "no", "desired_purchase_date": "Within 7 days",
        "name": "Jay", "mobile": "9000002002",
    })
    modes = sorted(g["match_mode"] for g in groups.list_groups())
    assert modes == ["exact", "flexible"], (
        "a buyer who insists on one brand cannot sit in a group that may buy any brand"
    )
