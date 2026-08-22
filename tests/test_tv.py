"""Television category: routing, specification, grouping and pricing."""
from __future__ import annotations

import pytest

from app import catalog
from app.nlu import rules
from app.services import groups, intents, pricing

from conftest import answer_all

TV = {
    "screen_size": "50-55 inch", "display_type": "LED", "resolution": "4K UHD",
    "smart_tv": "Smart TV", "preferred_brand": "Samsung", "brand_flexible": "yes",
    "usage": "Hotel rooms", "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "Within 7 days", "can_wait": "yes",
    "wall_mount": "yes",
}


def buy(chat, session, opening, name, mobile, **over):
    return answer_all(chat, session, opening, {**TV, **over, "name": name, "mobile": mobile})


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "I need 5 TV", "2 televisions", "5 Samsung 43 inch 4K TV",
    "10 smart tv for hotel", "OLED tv", "led tv", "qled television",
])
def test_tv_requests_route_to_the_tv_flow(text):
    assert catalog.detect(text, allow_fallback=True) == "TV"


@pytest.mark.parametrize("text", [
    "digital signage", "video wall", "I need a projector",
    "commercial display", "interactive panel", "20 monitors",
])
def test_commercial_display_hardware_is_not_a_tv(text):
    """A different purchase, quoted differently -- it waits for a real quote
    in the open-ended flow rather than being priced off a consumer TV table."""
    assert catalog.detect(text, allow_fallback=True) == "GENERAL"


def test_tv_does_not_steal_other_categories():
    assert catalog.detect("I need 2 AC") == "AC"
    assert catalog.detect("3 fridge") == "FRIDGE"


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,qty", [
    ("I need 5 TV", 5),
    ("2 televisions", 2),
    ("5 Samsung 43 inch 4K TV", 5),      # 43 is the size, 5 is the order
    ("10 smart tv for hotel", 10),
])
def test_quantity_is_not_confused_with_screen_size(text, qty):
    assert rules.extract(text, {})["quantity"] == qty


@pytest.mark.parametrize("text,slot,value", [
    ('55 inch', "screen_size", "50-55 inch"),
    ('32"', "screen_size", "32 inch"),
    ("65 inch", "screen_size", "65 inch+"),
    ("qled", "display_type", "QLED"),
    ("oled please", "display_type", "OLED"),
    ("normal led", "display_type", "LED"),
    ("4k", "resolution", "4K UHD"),
    ("full hd", "resolution", "Full HD"),
    ("android tv", "smart_tv", "Smart TV"),
])
def test_specifications_are_understood(text, slot, value):
    slots = rules.extract(text, {"category": "TV"}, expecting=slot)
    assert slots.get(slot) == value


def test_qled_is_not_read_as_led():
    """A bare 'led' pattern would swallow QLED and OLED and merge three very
    differently priced products into one group."""
    for text, expected in [("qled", "QLED"), ("oled", "OLED"), ("led", "LED")]:
        slots = rules.extract(text, {"category": "TV"}, expecting="display_type")
        assert slots.get("display_type") == expected, text


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #
def test_tv_flow_collects_its_specification_and_prices_it(chat):
    reply = buy(chat, "tv1", "I need 8 TV", "Rahul", "9876540001")
    assert reply["done"] is True

    intent = intents.get_full(reply["summary"]["intent_id"])
    assert intent["category"] == "TV"
    assert intent["quantity"] == 8
    assert intent["unit"] == "TV"
    for part in ("50-55 inch", "LED", "4K UHD"):
        assert part in intent["product"], intent["product"]

    group = groups.list_groups()[0]
    assert group["current_price"] == 40400, "8 TVs sit in the 6-10 slab"
    assert group["next_target_qty"] == 11


def test_tv_question_order(chat):
    chat("tv2", "")
    reply = chat("tv2", "I need 8 TV")
    order = []
    for _ in range(18):
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        order.append(question["slot"])
        reply = chat("tv2", {**TV, "name": "Asha", "mobile": "9876540002"}.get(question["slot"])
                     or (question["chips"][0]["value"] if question["chips"] else "skip"))

    assert order[:4] == ["mobile", "screen_size", "display_type", "resolution"], order
    assert order.index("preferred_brand") < order.index("city")
    assert order[-1] == "name"


# --------------------------------------------------------------------------- #
# grouping
# --------------------------------------------------------------------------- #
def test_same_specification_pools(chat):
    buy(chat, "tv3", "I need 4 TV", "A", "9876540003")
    buy(chat, "tv4", "I need 3 TV", "B", "9876540004")

    open_groups = groups.list_groups()
    assert len(open_groups) == 1, [g["code"] for g in open_groups]
    assert open_groups[0]["strong_intent_qty"] == 7
    assert open_groups[0]["current_price"] == 40400


@pytest.mark.parametrize("difference", [
    {"screen_size": "32 inch", "resolution": "HD Ready"},
    {"display_type": "OLED"},
    {"resolution": "Full HD"},
])
def test_different_specifications_do_not_pool(chat, difference):
    """A 55-inch OLED and a 32-inch LED are not the same purchase."""
    buy(chat, "tv5", "I need 4 TV", "A", "9876540005")
    buy(chat, "tv6", "I need 4 TV", "B", "9876540006", **difference)

    assert len(groups.list_groups()) == 2
    assert groups.consolidate()["groups_merged"] == 0


def test_panel_technology_is_priced_separately(chat):
    """OLED costs roughly three times LED; sharing a slab table would be wrong."""
    buy(chat, "tv7", "I need 4 TV", "A", "9876540007")
    buy(chat, "tv8", "I need 4 TV", "B", "9876540008", display_type="OLED")

    prices = sorted(g["current_price"] for g in groups.list_groups())
    assert prices == [42000, 125000]


def test_the_group_is_named_from_the_specification(chat):
    buy(chat, "tv9", "I need 4 TV", "A", "9876540009")
    assert pricing.group_label(groups.list_groups()[0]) == \
        "Ahmedabad – 50-55 inch LED 4K UHD TV"
