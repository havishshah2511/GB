"""Demo data so the dashboard and the group-buying loop are visible on first run.

Idempotent: does nothing once any customer exists. Disable with SEED_DEMO_DATA=0.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from .db import query_one, today
from .services import intents, notifications

log = logging.getLogger("groupbuy.seed")


def _date(days: int) -> str:
    return str(today() + timedelta(days=days))


# The Ahmedabad AC group deliberately starts at 18 units: a new visitor asking
# for 2 ACs reproduces the 18 -> 20 story from the product spec.
DEMO_INTENTS: list[dict[str, Any]] = [
    # --- Ahmedabad · 1.5 Ton Split Inverter AC (flexible brand) -------------
    {"category": "AC", "quantity": 4, "city": "Ahmedabad", "area": "Satellite",
     "name": "Neha Patel", "mobile": "9820011001", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "Daikin",
     "brand_flexible": True, "star_rating": "5 Star",
     "desired_purchase_date": _date(7), "maximum_purchase_date": _date(16), "can_wait": True},
    {"category": "AC", "quantity": 6, "city": "Ahmedabad", "area": "Bopal",
     "name": "Vikram Shah", "mobile": "9820011002", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "No Preference",
     "brand_flexible": True, "desired_purchase_date": _date(10),
     "maximum_purchase_date": _date(20), "can_wait": True},
    {"category": "AC", "quantity": 5, "city": "Ahmedabad", "area": "Maninagar",
     "name": "Sanjay Desai", "mobile": "9820011003", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "Voltas",
     "brand_flexible": True, "desired_purchase_date": _date(12),
     "maximum_purchase_date": _date(19), "can_wait": True},
    {"category": "AC", "quantity": 3, "city": "Ahmedabad", "area": "Satellite",
     "name": "Farhan Qureshi", "mobile": "9820011004", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "LG",
     "brand_flexible": True, "installation_required": True,
     "desired_purchase_date": _date(9), "maximum_purchase_date": _date(18), "can_wait": True},

    # --- Ahmedabad · Daikin-only buyers form their own exact group ----------
    {"category": "AC", "quantity": 2, "city": "Ahmedabad", "area": "Prahlad Nagar",
     "name": "Ritu Mehta", "mobile": "9820011005", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "Daikin",
     "brand_flexible": False, "desired_purchase_date": _date(8),
     "maximum_purchase_date": _date(14), "can_wait": True},

    # --- Mumbai · 1.5 Ton Split Inverter AC ---------------------------------
    {"category": "AC", "quantity": 3, "city": "Mumbai", "area": "Andheri",
     "name": "Kiran Rao", "mobile": "9820011006", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "Hitachi",
     "brand_flexible": True, "desired_purchase_date": _date(11),
     "maximum_purchase_date": _date(21), "can_wait": True},
    {"category": "AC", "quantity": 2, "city": "Mumbai", "area": "Powai",
     "name": "Aditi Joshi", "mobile": "9820011007", "capacity": "1.5 Ton",
     "ac_type": "Split", "inverter": "Inverter", "preferred_brand": "No Preference",
     "brand_flexible": True, "desired_purchase_date": _date(6),
     "maximum_purchase_date": _date(15), "can_wait": True},

    # --- Ahmedabad · Premium Basmati rice -----------------------------------
    {"category": "RICE", "quantity": 400, "city": "Ahmedabad", "area": "Navrangpura",
     "name": "Hotel Rasoi", "mobile": "9820011008", "rice_type": "Basmati",
     "grade": "Premium", "usage": "Restaurant", "brand_preference": "India Gate",
     "brand_flexible": True, "recurring_monthly": True, "package_size": "25 kg",
     "desired_purchase_date": _date(5), "maximum_purchase_date": _date(13), "can_wait": True},
    {"category": "RICE", "quantity": 250, "city": "Ahmedabad", "area": "Vastrapur",
     "name": "Gokul Caterers", "mobile": "9820011009", "rice_type": "Basmati",
     "grade": "Premium", "usage": "Catering", "brand_preference": "No Preference",
     "brand_flexible": True, "desired_purchase_date": _date(8),
     "maximum_purchase_date": _date(18), "can_wait": True},
    {"category": "RICE", "quantity": 100, "city": "Ahmedabad", "area": "Satellite",
     "name": "Meera Iyer", "mobile": "9820011010", "rice_type": "Basmati",
     "grade": "Premium", "usage": "Personal", "brand_preference": "Daawat",
     "brand_flexible": True, "desired_purchase_date": _date(6),
     "maximum_purchase_date": _date(12), "can_wait": True},
]


def seed_demo() -> bool:
    row = query_one("SELECT COUNT(*) AS n FROM customers")
    if row and int(row["n"]) > 0:
        return False

    # Backfilling ten intents at once would otherwise fire every price-drop and
    # near-target message at boot.
    with notifications.suppressed():
        for record in DEMO_INTENTS:
            try:
                intents.create(dict(record))
            except Exception:
                log.exception("failed to seed demo intent for %s", record.get("name"))

    log.info("seeded %d demo purchase intents", len(DEMO_INTENTS))
    return True
