"""Operator-triggered data reset.

Reachable on a public deployment, so it is guarded by admin auth, a typed
confirmation phrase, and an environment switch.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import customers, groups, intents, pricing

from conftest import answer_all

AC = {
    "capacity": "1.5 Ton", "ac_type": "Split", "inverter": "Inverter",
    "preferred_brand": "Daikin", "brand_flexible": "yes", "city": "Ahmedabad",
    "area": "Satellite", "desired_purchase_date": "Within 7 days", "can_wait": "yes",
}

PHRASE = "DELETE ALL DATA"


@pytest.fixture
def populated(chat):
    answer_all(chat, "z1", "I need 4 AC", {**AC, "name": "Ravi", "mobile": "9000070001"})
    answer_all(chat, "z2", "I need 6 AC", {**AC, "name": "Sunita", "mobile": "9000070002"})
    assert groups.list_groups(), "fixture failed to create data"
    return True


def counts():
    return {
        "customers": len(customers.list_customers()),
        "intents": len(intents.list_intents()),
        "groups": len(groups.list_groups()),
    }


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #
def test_reset_requires_the_confirmation_phrase(client, populated):
    before = counts()
    response = client.post("/api/admin/maintenance/reset")
    assert response.status_code == 400
    assert PHRASE in response.json()["detail"]
    assert counts() == before, "data was touched without confirmation"


def test_a_wrong_phrase_is_refused(client, populated):
    before = counts()
    assert client.post("/api/admin/maintenance/reset?confirm=delete").status_code == 400
    assert client.post("/api/admin/maintenance/reset?confirm=yes").status_code == 400
    assert counts() == before


def test_reset_requires_admin_auth(populated):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anonymous:      # no credentials
        response = anonymous.post(
            f"/api/admin/maintenance/reset?confirm={PHRASE.replace(' ', '%20')}"
        )
    assert response.status_code in (401, 403)
    assert counts()["customers"] == 2, "anonymous caller deleted data"


def test_reset_can_be_disabled_for_production(client, populated, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_DATA_RESET", False)
    response = client.post("/api/admin/maintenance/reset", params={"confirm": PHRASE})
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()
    assert counts()["customers"] == 2


# --------------------------------------------------------------------------- #
# behaviour
# --------------------------------------------------------------------------- #
def test_reset_clears_everything(client, populated):
    response = client.post("/api/admin/maintenance/reset", params={"confirm": PHRASE})
    assert response.status_code == 200

    body = response.json()
    assert body["before"]["customers"] == 2
    assert body["deleted"]["purchase_intents"] == 2

    assert counts() == {"customers": 0, "intents": 0, "groups": 0}


def test_pricing_templates_survive_so_the_app_still_works(client, populated, chat):
    client.post("/api/admin/maintenance/reset", params={"confirm": PHRASE})
    assert pricing.template_slabs("AC|1.5_ton|split|inverter"), "slab templates were lost"

    # A brand new request must price correctly straight after a reset.
    reply = answer_all(chat, "z3", "I need 2 AC", {**AC, "name": "Neha", "mobile": "9000070003"})
    assert reply["done"] is True
    assert groups.list_groups()[0]["current_price"] == 40000


def test_keep_customers_deletes_only_their_requests(client, populated):
    response = client.post(
        "/api/admin/maintenance/reset",
        params={"confirm": PHRASE, "keep_customers": "true"},
    )
    assert response.status_code == 200

    after = counts()
    assert after["customers"] == 2, "customers should have been kept"
    assert after["intents"] == 0 and after["groups"] == 0


def test_reset_is_written_to_the_audit_log(client, populated):
    client.post("/api/admin/maintenance/reset", params={"confirm": PHRASE})
    entries = client.get("/api/admin/audit").json()["entries"]
    assert any(e["action"] == "reset" for e in entries), "destructive action not audited"


def test_group_codes_restart_after_a_reset(client, populated, chat):
    client.post("/api/admin/maintenance/reset", params={"confirm": PHRASE})
    answer_all(chat, "z4", "I need 2 AC", {**AC, "name": "Amit", "mobile": "9000070004"})
    assert groups.list_groups()[0]["code"].endswith("-001")
