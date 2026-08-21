"""Rules-based extraction (spec section 3: never re-ask what was already said)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app import nlu
from app.db import today
from app.nlu import rules


def test_extracts_everything_from_the_spec_example():
    text = "I need two Daikin 1.5 ton ACs in Ahmedabad next week."
    slots = rules.extract(text, {})
    assert slots["category"] == "AC"
    assert slots["quantity"] == 2
    assert slots["capacity"] == "1.5 Ton"
    assert slots["preferred_brand"] == "Daikin"
    assert slots["city"] == "Ahmedabad"
    assert slots["desired_purchase_date"] == str(today() + timedelta(days=7))


def test_quantity_survives_words_between_number_and_product():
    slots = rules.extract("I need 2 Daikin 1.5 ton split inverter AC", {})
    assert slots["quantity"] == 2
    assert slots["capacity"] == "1.5 Ton"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I need 3 fridge", 3),
        ("2 refrigerators please", 2),
        ("I need 4 LG double door fridges", 4),
        # A spec figure is not a quantity: 300 is the size, 3 is the order.
        ("I need 3 fridge 300 L", 3),
        ("3 fridge 5 star", 3),
    ],
)
def test_fridge_quantities_are_counted_in_units(text, expected):
    slots = rules.extract(text, {})
    assert slots["category"] == "FRIDGE"
    assert slots["quantity"] == expected


def test_capacity_is_not_mistaken_for_quantity():
    slots = rules.extract("1.5 ton split inverter AC", {})
    assert slots["capacity"] == "1.5 Ton"
    assert "quantity" not in slots


def test_mobile_number_is_not_read_as_a_quantity():
    slots = rules.extract("9876543210", {"category": "AC"}, expecting="mobile")
    assert slots["mobile"] == "9876543210"
    assert "quantity" not in slots


@pytest.mark.parametrize(
    "raw,expected",
    [("+91 98765 43210", "9876543210"), ("098765-43210", "9876543210"),
     ("919876543210", "9876543210"), ("12345", None), ("1234567890", None)],
)
def test_mobile_normalisation(raw, expected):
    from app.utils import normalise_mobile

    assert normalise_mobile(raw) == expected


@pytest.mark.parametrize(
    "text,days",
    [("immediately", 0), ("within 3 days", 3), ("within 7 days", 7),
     ("next week", 7), ("within 15 days", 15), ("next month", 30), ("tomorrow", 1)],
)
def test_purchase_timing_phrases(text, days):
    when, _ = rules.extract_date(text)
    assert when == today() + timedelta(days=days)


def test_absolute_dates():
    when, _ = rules.extract_date("2026-09-10")
    assert str(when) == "2026-09-10"


def test_existing_answers_are_not_overwritten_by_a_later_sweep():
    state = {"category": "AC", "quantity": 2, "city": "Ahmedabad"}
    slots = rules.extract("Mumbai has better dealers though", state)
    assert "city" not in slots  # already known -> not re-extracted


def test_expecting_biases_a_bare_answer():
    assert rules.extract("2", {"category": "AC"}, expecting="quantity")["quantity"] == 2
    assert rules.extract("1.5", {"category": "AC"}, expecting="capacity")["capacity"] == "1.5 Ton"


def test_message_intents():
    assert rules.detect_message_intent("how does this work?") == "explain"
    assert rules.detect_message_intent("I am ready to buy") == "ready_to_buy"
    assert rules.detect_message_intent("start over") == "restart"
    # "stop"-style phrasings resolve to the cancel command, which the
    # conversation engine acts on at any stage (see test_commands.py).
    assert rules.detect_message_intent("no longer required") == "cancel"
    assert rules.detect_message_intent("show me my old request") == "show_past"


def test_wait_flexibility():
    assert rules.extract_wait("yes") == (True, 7)
    assert rules.extract_wait("maybe") == (True, 4)
    assert rules.extract_wait("no, I need it by then") == (False, 0)
    assert rules.extract_wait("I can wait 10 days") == (True, 10)


def test_engine_falls_back_to_rules_without_an_api_key():
    assert nlu.engine_name() == "rules"


def test_typos_still_resolve():
    slots = rules.extract("need 2 diakin ac in amdavad", {})
    assert slots["preferred_brand"] == "Daikin"
    assert slots["city"] == "Ahmedabad"
    assert slots["quantity"] == 2
