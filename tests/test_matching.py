"""Intent matching and group aggregation (spec sections 10-12)."""
from __future__ import annotations

from datetime import timedelta

from app.db import today
from app.services import groups, intents, matching


def make_intent(**overrides):
    state = {
        "category": "AC", "quantity": 2, "city": "Ahmedabad", "area": "Satellite",
        "name": "Test Buyer", "mobile": "9800000001",
        "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
        "preferred_brand": "Daikin", "brand_flexible": True,
        "desired_purchase_date": str(today() + timedelta(days=7)),
        "maximum_purchase_date": str(today() + timedelta(days=17)),
        "can_wait": True,
    }
    state.update(overrides)
    return intents.create(state)


def test_first_intent_creates_a_group():
    result = make_intent()
    assert result["group_created"] is True
    assert result["group"]["current_qty"] == 2
    assert result["group"]["code"].startswith("AC-AHM-")


def test_compatible_intents_merge_and_quantities_add_up():
    """Spec section 12: 18 existing + 2 new = 20."""
    make_intent(quantity=18, mobile="9800000002", name="Big Buyer")
    result = make_intent(quantity=2, mobile="9800000003", name="Small Buyer")

    assert result["group_created"] is False
    assert result["group"]["current_qty"] == 20
    assert result["group"]["strong_intent_qty"] == 20
    assert result["group"]["current_price"] == 37000       # 11-20 slab
    assert result["group"]["next_target_qty"] == 21
    assert result["group"]["next_price"] == 35500


def test_different_capacity_never_merges():
    a = make_intent(capacity="1.5 Ton", mobile="9800000004")
    b = make_intent(capacity="2 Ton", mobile="9800000005")
    assert a["group"]["id"] != b["group"]["id"]


def test_different_city_never_merges():
    a = make_intent(city="Ahmedabad", mobile="9800000006")
    b = make_intent(city="Mumbai", mobile="9800000007")
    assert a["group"]["id"] != b["group"]["id"]


def test_brand_locked_buyer_gets_an_exact_group():
    flexible = make_intent(mobile="9800000008", brand_flexible=True)
    locked = make_intent(mobile="9800000009", preferred_brand="Daikin", brand_flexible=False)

    assert locked["group"]["id"] != flexible["group"]["id"]
    assert locked["group"]["match_mode"] == "exact"
    assert flexible["group"]["match_mode"] == "flexible"


def test_brand_locked_buyers_of_the_same_brand_pool_together():
    a = make_intent(mobile="9800000010", preferred_brand="Daikin", brand_flexible=False)
    b = make_intent(mobile="9800000011", preferred_brand="Daikin", brand_flexible=False, quantity=3)
    assert a["group"]["id"] == b["group"]["id"]
    assert b["group"]["current_qty"] == 5


def test_brand_locked_buyers_of_different_brands_stay_apart():
    a = make_intent(mobile="9800000012", preferred_brand="Daikin", brand_flexible=False)
    b = make_intent(mobile="9800000013", preferred_brand="LG", brand_flexible=False)
    assert a["group"]["id"] != b["group"]["id"]


def test_flexible_buyer_prefers_the_larger_group():
    """Momentum: joining the bigger pool unlocks a better price for everyone."""
    big = make_intent(mobile="9800000015", quantity=18, preferred_brand="No Preference")
    small = make_intent(mobile="9800000014", quantity=2, preferred_brand="Daikin",
                        brand_flexible=False)          # brand-locked -> its own group
    assert small["group"]["id"] != big["group"]["id"]

    joiner = make_intent(mobile="9800000016", quantity=3, preferred_brand="Daikin",
                         brand_flexible=True)          # compatible with both
    assert joiner["group"]["id"] == big["group"]["id"]


def test_buyer_without_a_brand_preference_can_join_a_brand_locked_group():
    """No preference means the group's locked brand is acceptable."""
    locked = make_intent(mobile="9800000026", quantity=4, preferred_brand="Daikin",
                         brand_flexible=False)
    agnostic = make_intent(mobile="9800000027", quantity=2, preferred_brand="No Preference")
    assert agnostic["group"]["id"] == locked["group"]["id"]
    assert agnostic["group"]["match_mode"] == "exact"


def test_non_overlapping_purchase_windows_do_not_merge():
    a = make_intent(
        mobile="9800000017",
        desired_purchase_date=str(today() + timedelta(days=2)),
        maximum_purchase_date=str(today() + timedelta(days=4)),
    )
    b = make_intent(
        mobile="9800000018",
        desired_purchase_date=str(today() + timedelta(days=40)),
        maximum_purchase_date=str(today() + timedelta(days=45)),
    )
    assert a["group"]["id"] != b["group"]["id"]


def test_wildcard_specification_can_join_any_compatible_group():
    known = make_intent(mobile="9800000019", capacity="1.5 Ton")
    unsure = make_intent(mobile="9800000020", capacity="Not Sure")
    assert unsure["group"]["id"] == known["group"]["id"]


def test_explain_reports_reasons_and_blockers():
    make_intent(mobile="9800000021", capacity="1.5 Ton")
    other = make_intent(mobile="9800000022", capacity="2 Ton")
    rows = matching.explain(intents.get(other["intent"]["id"]))
    blocked = [r for r in rows if not r["compatible"]]
    assert blocked and any("capacity" in b for r in blocked for b in r["blockers"])


def test_expired_intents_leave_the_group_quantity():
    first = make_intent(quantity=10, mobile="9800000023")
    second = make_intent(quantity=5, mobile="9800000024")
    group_id = second["group"]["id"]
    assert groups.get(group_id)["current_qty"] == 15

    intents.set_status(second["intent"]["id"], "expired")
    assert groups.get(group_id)["current_qty"] == 10


def test_only_strong_intents_drive_the_price():
    result = make_intent(quantity=25, mobile="9800000025")
    group_id = result["group"]["id"]
    assert groups.get(group_id)["strong_intent_qty"] == 25

    intents.set_strength(result["intent"]["id"], "intent")   # no mobile-grade confidence
    group = groups.get(group_id)
    assert group["current_qty"] == 25
    assert group["strong_intent_qty"] == 0
    assert group["current_price"] == 40000                   # falls back to slab 1
