"""Pricing engine — the single source of every number the customer sees."""
from __future__ import annotations

import pytest

from app.services import pricing

SLABS = [
    {"id": "a", "minimum_qty": 1, "maximum_qty": 5, "price": 40000, "price_status": "indicative"},
    {"id": "b", "minimum_qty": 6, "maximum_qty": 10, "price": 38500, "price_status": "indicative"},
    {"id": "c", "minimum_qty": 11, "maximum_qty": 20, "price": 37000, "price_status": "indicative"},
    {"id": "d", "minimum_qty": 21, "maximum_qty": 30, "price": 35500, "price_status": "indicative"},
    {"id": "e", "minimum_qty": 31, "maximum_qty": 50, "price": 34000, "price_status": "indicative"},
    {"id": "f", "minimum_qty": 51, "maximum_qty": None, "price": 32500, "price_status": "indicative"},
]


@pytest.mark.parametrize(
    "qty,price,next_qty,next_price,gap",
    [
        (0, 40000, 1, 40000, 1),
        (1, 40000, 6, 38500, 5),
        (5, 40000, 6, 38500, 1),
        (6, 38500, 11, 37000, 5),
        (20, 37000, 21, 35500, 1),
        (21, 35500, 31, 34000, 10),
        (50, 34000, 51, 32500, 1),
        (51, 32500, None, None, None),
        (900, 32500, None, None, None),
    ],
)
def test_slab_selection(qty, price, next_qty, next_price, gap):
    result = pricing.calculate(SLABS, qty)
    assert result["current_price"] == price
    assert result["next_target_qty"] == next_qty
    assert result["next_price"] == next_price
    assert result["gap_to_next_price"] == gap


def test_savings_are_relative_to_the_reference_price():
    result = pricing.calculate(SLABS, 20, customer_qty=2)
    assert result["reference_price"] == 40000
    assert result["saving_per_unit"] == 3000          # 40000 - 37000
    assert result["customer_saving"] == 6000          # spec section 14
    assert result["next_saving_per_unit"] == 1500     # 37000 - 35500
    assert result["customer_next_saving"] == 3000     # spec section 15


def test_top_slab_has_no_next_target():
    result = pricing.calculate(SLABS, 60, customer_qty=3)
    assert result["is_top_slab"] is True
    assert result["next_target_qty"] is None
    assert result["next_saving_per_unit"] == 0
    assert result["customer_next_saving"] == 0


def test_no_slabs_means_no_prices_rather_than_invented_ones():
    result = pricing.calculate([], 25, customer_qty=2)
    assert result["has_pricing"] is False
    assert result["current_price"] is None
    assert result["reference_price"] is None
    assert result["saving_per_unit"] == 0


def test_price_facts_expose_the_slab_floor_for_progress_meters():
    from app.services import groups, intents
    from datetime import timedelta
    from app.db import today

    result = intents.create({
        "category": "AC", "quantity": 20, "city": "Ahmedabad",
        "name": "Meter Test", "mobile": "9899000001",
        "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
        "brand_flexible": True,
        "desired_purchase_date": str(today() + timedelta(days=7)),
        "maximum_purchase_date": str(today() + timedelta(days=17)),
    })
    facts = pricing.price_facts(groups.get(result["group"]["id"]), 2)
    assert facts["current_slab_min_qty"] == 11        # 11-20 band
    assert facts["next_target_qty"] == 21
    # A meter drawn from the floor shows 9/10, not 20/21.
    span = facts["next_target_qty"] - facts["current_slab_min_qty"]
    assert span == 10


def test_price_facts_never_leak_numbers_when_pricing_is_missing():
    group = {
        "id": "GRP-X", "code": "X", "product_category": "AC", "city": "Ahmedabad",
        "product_specification": '{"capacity": "1.5 Ton"}', "strong_intent_qty": 4,
        "supplier_price_confirmed": 0,
    }
    facts = pricing.price_facts(group, 2)
    assert facts["has_pricing"] is False
    assert "current_price_text" not in facts
    assert "next_price_text" not in facts
