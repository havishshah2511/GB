"""Commercial solar panels: routing, capacity in kW, scope-based pricing."""
from __future__ import annotations

import pytest

from app import catalog
from app.nlu import rules
from app.services import groups, intents, pricing

from conftest import answer_all

SOLAR = {
    "module_type": "Mono PERC", "scope": "Installed system", "mounting": "Rooftop",
    "panel_wattage": "550-600 Wp", "preferred_brand": "Waaree", "brand_flexible": "yes",
    "site_type": "Factory", "dcr": "DCR required",
    "city": "Ahmedabad", "area": "Naroda",
    "desired_purchase_date": "Within 30 days", "can_wait": "yes",
}


def buy(chat, session, opening, name, mobile, **over):
    return answer_all(chat, session, opening, {**SOLAR, **over, "name": name, "mobile": mobile})


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "I need 100 kW solar", "250 kw rooftop solar plant", "solar panels for factory",
    "2 MW solar", "topcon modules", "bifacial panels", "photovoltaic system",
])
def test_solar_requests_route_to_the_solar_flow(text):
    assert catalog.detect(text, allow_fallback=True) == "SOLAR"


@pytest.mark.parametrize("text", [
    "solar water heater", "solar inverter", "solar street light", "solar battery",
    "solar cable", "solar charge controller", "solar pump",
])
def test_the_rest_of_the_solar_family_is_not_a_module_purchase(text):
    """Priced on a different basis entirely, so it waits for a real quote in
    the open-ended flow rather than being priced per kW."""
    assert catalog.detect(text, allow_fallback=True) == "GENERAL"


def test_solar_does_not_steal_other_categories():
    assert catalog.detect("I need 2 AC") == "AC"
    assert catalog.detect("5 TV") == "TV"
    assert catalog.detect("3 fridge") == "FRIDGE"


# --------------------------------------------------------------------------- #
# capacity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,kw", [
    ("I need 100 kW solar", 100),
    ("250 kwp", 250),
    ("50 kilowatt", 50),
    ("2 MW solar", 2000),          # megawatts convert to kW
    ("1.5 MW rooftop", 1500),
])
def test_capacity_is_read_in_kw(text, kw):
    assert rules.extract_quantity(text, catalog.get("SOLAR")) == kw


def test_a_panel_count_is_not_treated_as_a_system_size():
    """"100 panels" is not 100 kW. Guessing a wattage would silently invent the
    quantity, so the bot asks instead."""
    assert rules.extract_quantity("I need 100 panels", catalog.get("SOLAR")) is None


@pytest.mark.parametrize("text,slot,value", [
    ("topcon", "module_type", "TOPCon"),
    ("bifacial", "module_type", "Bifacial"),
    ("mono perc", "module_type", "Mono PERC"),
    ("epc turnkey", "scope", "Installed system"),
    ("panels only", "scope", "Panels only"),
    ("ground mount", "mounting", "Ground mount"),
    ("factory roof", "mounting", "Rooftop"),
])
def test_specifications_are_understood(text, slot, value):
    slots = rules.extract(text, {"category": "SOLAR"}, expecting=slot)
    assert slots.get(slot) == value


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #
def test_solar_flow_collects_its_specification_and_prices_per_kw(chat):
    reply = buy(chat, "sol1", "I need 150 kW solar", "Havish", "9812300111")
    assert reply["done"] is True

    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["category"] == "SOLAR"
    assert intent["quantity"] == 150
    assert intent["unit"] == "kW"

    group = groups.list_groups()[0]
    assert group["current_price"] == 42000, "150 kW installed sits in the 101-250 slab"
    assert group["next_target_qty"] == 251


def test_solar_question_order(chat):
    chat("sol2", "")
    reply = chat("sol2", "I need 150 kW solar")
    order = []
    for _ in range(18):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        order.append(question["slot"])
        reply = chat("sol2", {**SOLAR, "name": "A", "mobile": "9812300112"}.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert order[:4] == ["mobile", "module_type", "scope", "mounting"], order
    assert order.index("preferred_brand") < order.index("city")
    assert order[-1] == "name"


def test_the_group_is_named_from_the_specification(chat):
    buy(chat, "sol3", "I need 150 kW solar", "A", "9812300113")
    label = pricing.group_label(groups.list_groups()[0])
    assert label == "Ahmedabad – Mono PERC Installed system Rooftop Solar"
    assert "kW" not in label, "the counting unit should not appear in the product name"


# --------------------------------------------------------------------------- #
# grouping and pricing
# --------------------------------------------------------------------------- #
def test_same_specification_pools_and_reprices(chat):
    buy(chat, "sol4", "I need 60 kW solar", "A", "9812300114")
    assert groups.list_groups()[0]["current_price"] == 45000   # 26-100 slab

    buy(chat, "sol5", "I need 80 kW solar", "B", "9812300115")

    open_groups = groups.list_groups()
    assert len(open_groups) == 1, [g["code"] for g in open_groups]
    assert open_groups[0]["strong_intent_qty"] == 140
    assert open_groups[0]["current_price"] == 42000, "140 kW crosses into 101-250"


def test_panels_only_and_installed_system_are_priced_separately(chat):
    """Supply and full EPC differ by roughly half; sharing a slab table would
    price one of them badly wrong."""
    buy(chat, "sol6", "I need 60 kW solar", "A", "9812300116")
    buy(chat, "sol7", "I need 60 kW solar", "B", "9812300117", scope="Panels only")

    prices = sorted(g["current_price"] for g in groups.list_groups())
    assert prices == [23000, 45000]
    assert groups.consolidate()["groups_merged"] == 0


def test_mounting_only_splits_an_installed_system(chat):
    """A module costs the same wherever it goes, so panels-only buyers pool
    across mountings; an installed system does not."""
    buy(chat, "sol8", "I need 60 kW solar", "A", "9812300118",
        scope="Panels only", mounting="Rooftop")
    buy(chat, "sol9", "I need 60 kW solar", "B", "9812300119",
        scope="Panels only", mounting="Ground mount")
    supply_prices = {g["current_price"] for g in groups.list_groups()}
    assert supply_prices == {23000}, "module price should not depend on mounting"


@pytest.mark.parametrize("difference", [
    {"module_type": "TOPCon"},
    {"module_type": "Bifacial"},
    {"scope": "Panels only"},
    {"mounting": "Ground mount"},
])
def test_different_specifications_do_not_pool(chat, difference):
    buy(chat, "sola", "I need 60 kW solar", "A", "9812300120")
    buy(chat, "solb", "I need 60 kW solar", "B", "9812300121", **difference)
    assert len(groups.list_groups()) == 2
    assert groups.consolidate()["groups_merged"] == 0


def test_a_megawatt_request_reaches_the_top_slab(chat):
    buy(chat, "sol10", "I need 2 MW solar", "A", "9812300122")
    group = groups.list_groups()[0]
    assert group["strong_intent_qty"] == 2000
    assert group["current_price"] == 36000, "2 MW is past the 1001 kW slab"
    assert group["next_target_qty"] is None, "already on the best slab"
