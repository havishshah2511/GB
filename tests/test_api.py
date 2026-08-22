"""HTTP surface (spec section 29) and admin operations (section 30)."""
from __future__ import annotations

from datetime import timedelta

from app import catalog
from app.db import today

INTENT_BODY = {
    "category": "AC",
    "quantity": 2,
    "city": "Ahmedabad",
    "area": "Satellite",
    "name": "Rahul",
    "mobile": "9876543210",
    "desired_purchase_date": str(today() + timedelta(days=7)),
    "maximum_purchase_date": str(today() + timedelta(days=17)),
    "can_wait": True,
    "specifications": {
        "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
        "preferred_brand": "Daikin", "brand_flexible": True,
    },
}


def create_intent(client, **overrides):
    body = {**INTENT_BODY, **overrides}
    response = client.post("/api/intents", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
def test_chat_endpoint_returns_messages_and_chips(client):
    response = client.post("/api/chat/message", json={"session_id": "api-sess-1", "message": ""})
    assert response.status_code == 200
    data = response.json()
    assert data["messages"] and data["chips"]
    assert data["stage"] == "collecting"


def test_chat_history_endpoint(client):
    client.post("/api/chat/message", json={"session_id": "api-sess-2", "message": ""})
    client.post("/api/chat/message", json={"session_id": "api-sess-2", "message": "I need 2 AC"})
    data = client.get("/api/chat/api-sess-2").json()
    assert len(data["messages"]) >= 3
    assert data["summary"]["quantity"] == 2


def test_catalog_endpoint_lists_every_category(client):
    data = client.get("/api/catalog").json()
    keys = {c["key"] for c in data["categories"]}
    # AC, refrigerator and TV have their own priced flows; GENERAL takes the rest.
    assert keys == {"AC", "FRIDGE", "TV", "GENERAL"}
    assert keys == set(catalog.CATEGORIES), "the API must expose the whole registry"


# --------------------------------------------------------------------------- #
# intents / groups / pricing
# --------------------------------------------------------------------------- #
def test_create_intent_returns_group_and_share_kit(client):
    data = create_intent(client)
    assert data["intent"]["intent_id"].startswith("INT-")
    assert data["group"]["code"].startswith("AC-AHM-")
    assert data["group"]["quantity"]["strong_intent_qty"] == 2
    assert data["share"]["url"].startswith("http")
    assert "wa.me" in data["share"]["whatsapp_url"]


def test_get_group_and_pricing(client):
    created = create_intent(client)
    code = created["group"]["code"]

    group = client.get(f"/api/groups/{code}?qty=2").json()
    assert group["quantity"]["total_intent_qty"] == 2
    assert group["pricing"]["current_price"] == 40000

    pricing = client.get(f"/api/groups/{code}/pricing?qty=2").json()
    assert len(pricing["slabs"]) == 6
    assert pricing["facts"]["your_quantity_text"] == "2 ACs"
    assert pricing["supplier_price_confirmed"] is False


def test_update_intent_repriced_the_group(client):
    created = create_intent(client)
    intent_id = created["intent"]["intent_id"]
    response = client.put(f"/api/intents/{intent_id}", json={"quantity": 25})
    assert response.status_code == 200
    assert response.json()["group"]["pricing"]["current_price"] == 35500


def test_match_endpoint_explains_candidates(client):
    create_intent(client, mobile="9876543211")
    second = create_intent(client, mobile="9876543212", quantity=3)
    data = client.post(f"/api/intents/{second['intent']['intent_id']}/match").json()
    assert data["group"]["code"]
    assert isinstance(data["candidates"], list)
    assert data["candidates"][0]["compatible"] is True


def test_join_group_moves_an_intent(client):
    a = create_intent(client, mobile="9876543213")
    b = create_intent(client, mobile="9876543214", city="Mumbai")
    response = client.post(
        f"/api/groups/{a['group']['code']}/join",
        json={"intent_id": b["intent"]["intent_id"]},
    )
    assert response.status_code == 200
    assert response.json()["group"]["quantity"]["total_intent_qty"] == 4


def test_recalculate_endpoint(client):
    created = create_intent(client)
    data = client.post(f"/api/groups/{created['group']['code']}/recalculate").json()
    assert data["group"]["code"] == created["group"]["code"]
    assert "price_changed" in data


def test_unknown_group_is_404(client):
    assert client.get("/api/groups/NOPE-000").status_code == 404


def test_invalid_intent_is_rejected(client):
    response = client.post("/api/intents", json={**INTENT_BODY, "quantity": 0})
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# referrals + landing
# --------------------------------------------------------------------------- #
def test_referral_creation_and_landing_page(client):
    created = create_intent(client)
    referral = client.post(
        "/api/referrals",
        json={"customer_id": _customer_id(client), "group_id": created["group"]["id"]},
    ).json()
    code = referral["referral_code"]

    page = client.get(f"/join/{created['group']['code']}?ref={code}")
    assert page.status_code == 200
    assert "invited you" in page.text
    assert created["group"]["label"] in page.text

    assert client.get(f"/api/referrals/{code}").json()["referral"]["clicks"] == 1


def _customer_id(client):
    return client.get("/api/admin/customers").json()["customers"][0]["id"]


def test_reconfirmation_links(client):
    created = create_intent(client)
    intent_id = created["intent"]["intent_id"]

    assert "still in" in client.get(f"/r/{intent_id}/yes").text
    assert client.get(f"/api/intents/{intent_id}").json()["record_status"] == "active"

    assert "Removed" in client.get(f"/r/{intent_id}/no").text
    assert client.get(f"/api/intents/{intent_id}").json()["record_status"] == "cancelled"


def test_notification_processing_endpoint(client):
    create_intent(client, mobile="9876543215", quantity=4)
    create_intent(client, mobile="9876543216", quantity=8)
    data = client.post("/api/notifications/process").json()
    assert data["sent"] >= 1
    assert data["failed"] == 0


# --------------------------------------------------------------------------- #
# admin
# --------------------------------------------------------------------------- #
def test_admin_requires_authentication(client):
    response = client.get("/api/admin/overview", auth=None)
    assert response.status_code == 401


def test_admin_overview_aggregates_demand(client):
    create_intent(client, mobile="9876543217", quantity=4)
    create_intent(client, mobile="9876543218", city="Mumbai", quantity=3)
    data = client.get("/api/admin/overview").json()

    assert data["intents"]["active"] == 2
    assert data["intents"]["demand_qty"] == 7
    assert {r["city"] for r in data["demand_by_city"]} == {"Ahmedabad", "Mumbai"}
    assert data["demand_by_product"][0]["category"] == "AC"
    assert data["engine"]["llm_enabled"] is False


def test_demand_by_product_reports_quantity_pending_to_close_a_price(client):
    """The back office has to answer 'how much more do we need?' per product."""
    create_intent(client, mobile="9876543230", quantity=4)      # AC, Ahmedabad
    create_intent(client, mobile="9876543231", city="Mumbai", quantity=2)

    products = client.get("/api/admin/demand-by-product").json()["products"]
    by_key = {p["category"]: p for p in products}

    assert "AC" in by_key and "FRIDGE" in by_key, "every category is listed, even empty ones"
    ac = by_key["AC"]
    assert ac["groups"] == 2
    assert ac["customers"] == 2
    assert ac["total_qty"] == 6
    assert ac["strong_qty"] == 6

    # 4 units sits in the 1-5 slab (next at 6, so 2 to go); 2 units needs 4 more.
    gaps = {row["code"]: row["pending_qty"] for row in ac["group_rows"]}
    assert sorted(gaps.values()) == [2, 4]
    assert ac["pending_qty"] == 6, "product-level pending is the sum of its groups"

    # Untouched category reports zeroes rather than being absent.
    assert by_key["FRIDGE"]["groups"] == 0
    assert by_key["FRIDGE"]["pending_qty"] == 0

    # Closest-to-closing group is listed first so an operator sees it at a glance.
    assert ac["group_rows"][0]["pending_qty"] == 2


def test_demand_by_product_is_empty_on_a_fresh_install(client):
    """No demo rows may ever appear in the back office."""
    products = client.get("/api/admin/demand-by-product").json()["products"]
    assert all(p["groups"] == 0 and p["total_qty"] == 0 for p in products)
    assert client.get("/api/admin/overview").json()["customers"] == 0


def test_admin_can_edit_slabs_and_reprice(client):
    created = create_intent(client, quantity=12)
    code = created["group"]["code"]
    response = client.put(
        f"/api/admin/groups/{code}/slabs",
        json={"slabs": [
            {"minimum_qty": 1, "maximum_qty": 9, "price": 39000},
            {"minimum_qty": 10, "maximum_qty": None, "price": 31000},
        ]},
    )
    assert response.status_code == 200
    assert response.json()["group"]["pricing"]["current_price"] == 31000


def test_admin_can_confirm_the_supplier_price(client):
    created = create_intent(client)
    code = created["group"]["code"]
    data = client.post(f"/api/admin/groups/{code}/supplier-price",
                       json={"confirmed": True, "supplier_id": "SUP-1"}).json()
    assert data["group"]["pricing"]["price_status"] == "supplier_confirmed"

    facts = client.get(f"/api/groups/{code}/pricing").json()
    assert facts["supplier_price_confirmed"] is True


def test_admin_can_merge_groups(client):
    a = create_intent(client, mobile="9876543219", quantity=4)
    b = create_intent(client, mobile="9876543220", city="Mumbai", quantity=6)
    data = client.post("/api/admin/groups/merge", json={
        "source_group_id": b["group"]["id"], "target_group_id": a["group"]["id"],
    }).json()
    assert data["group"]["quantity"]["total_intent_qty"] == 10


def test_admin_can_split_a_group(client):
    a = create_intent(client, mobile="9876543221", quantity=4)
    b = create_intent(client, mobile="9876543222", quantity=6)
    assert a["group"]["id"] == b["group"]["id"]

    data = client.post(f"/api/admin/groups/{a['group']['code']}/split", json={
        "intent_ids": [b["intent"]["intent_id"]],
    }).json()
    assert data["new_group"]["quantity"]["total_intent_qty"] == 6
    assert data["source_group"]["quantity"]["total_intent_qty"] == 4


def test_admin_can_correct_an_ai_extraction(client):
    created = create_intent(client)
    intent_id = created["intent"]["intent_id"]
    response = client.put(f"/api/admin/intents/{intent_id}",
                          json={"quantity": 9, "area": "Bopal", "rematch": True})
    assert response.status_code == 200
    detail = client.get(f"/api/admin/intents/{intent_id}").json()
    assert detail["intent"]["quantity"] == 9
    assert detail["intent"]["area"] == "Bopal"
    assert detail["match_candidates"]


def test_admin_can_move_an_intent_between_groups(client):
    a = create_intent(client, mobile="9876543223", quantity=4)
    b = create_intent(client, mobile="9876543224", city="Mumbai", quantity=6)
    response = client.post("/api/admin/intents/move", json={
        "intent_id": b["intent"]["intent_id"], "target_group_id": a["group"]["code"],
    })
    assert response.status_code == 200
    assert response.json()["target_group"]["quantity"]["total_intent_qty"] == 10


def test_admin_can_change_intent_status_and_strength(client):
    created = create_intent(client)
    intent_id = created["intent"]["intent_id"]

    client.post(f"/api/admin/intents/{intent_id}/strength?strength=ready_to_buy")
    assert client.get(f"/api/intents/{intent_id}").json()["status"] == "ready_to_buy"

    client.post(f"/api/admin/intents/{intent_id}/status?new_status=cancelled")
    assert client.get(f"/api/intents/{intent_id}").json()["record_status"] == "cancelled"


def test_admin_can_broadcast_to_a_group(client):
    create_intent(client, mobile="9876543225", quantity=4)
    created = create_intent(client, mobile="9876543226", quantity=3)
    data = client.post(f"/api/admin/groups/{created['group']['code']}/notify",
                       json={"message": "Supplier quote locked."}).json()
    assert data["queued"] == 2


def test_admin_conversation_viewer(client):
    client.post("/api/chat/message", json={"session_id": "api-conv", "message": ""})
    client.post("/api/chat/message", json={"session_id": "api-conv", "message": "I need 2 AC"})
    data = client.get("/api/admin/conversations/api-conv").json()
    assert data["conversation"]["extracted_information"]["quantity"] == 2
    assert len(data["conversation"]["messages"]) >= 3


def test_admin_audit_records_operations(client):
    created = create_intent(client)
    client.post(f"/api/admin/groups/{created['group']['code']}/supplier-price",
                json={"confirmed": True})
    entries = client.get("/api/admin/audit").json()["entries"]
    assert any(e["action"] == "supplier_price" for e in entries)


def test_health_endpoint(client):
    data = client.get("/health").json()
    assert data["status"] == "ok"
    assert data["nlu_engine"] == "rules"
