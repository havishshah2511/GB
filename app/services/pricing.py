"""Pricing engine.

Every price, saving and target in the product comes from this module. The AI
layer is never allowed to compute or invent a number -- it only renders what
these functions return.
"""
from __future__ import annotations

from typing import Any

from .. import catalog
from ..db import dumps, execute, insert, new_id, now_iso, query, query_one
from ..utils import money, qty_str


# --------------------------------------------------------------------------- #
# slab storage
# --------------------------------------------------------------------------- #
def seed_product_slabs() -> None:
    """Load the catalog's slab templates into pricing_slabs (idempotent)."""
    for category in catalog.all_categories():
        for product_key, slabs in category.slabs.items():
            existing = query_one(
                "SELECT COUNT(*) AS n FROM pricing_slabs WHERE product_key = ? AND group_id IS NULL",
                (product_key,),
            )
            if existing and existing["n"]:
                continue
            for slab in slabs:
                insert(
                    "pricing_slabs",
                    {
                        "id": new_id("SLAB", width=6, start=1),
                        "group_id": None,
                        "product_key": product_key,
                        "minimum_qty": slab.minimum_qty,
                        "maximum_qty": slab.maximum_qty,
                        "price": slab.price,
                        "price_status": "indicative",
                        "supplier_id": None,
                        "created_at": now_iso(),
                    },
                )


def template_slabs(product_key: str) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM pricing_slabs WHERE product_key = ? AND group_id IS NULL "
        "ORDER BY minimum_qty",
        (product_key,),
    )
    return [dict(r) for r in rows]


def group_slabs(group_id: str) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM pricing_slabs WHERE group_id = ? ORDER BY minimum_qty",
        (group_id,),
    )
    return [dict(r) for r in rows]


def clone_slabs_to_group(group_id: str, product_key: str) -> list[dict[str, Any]]:
    """Groups own a private copy of the slabs so admins can tune one group
    without disturbing the product-wide template."""
    if group_slabs(group_id):
        return group_slabs(group_id)
    for slab in template_slabs(product_key):
        insert(
            "pricing_slabs",
            {
                "id": new_id("SLAB", width=6, start=1),
                "group_id": group_id,
                "product_key": product_key,
                "minimum_qty": slab["minimum_qty"],
                "maximum_qty": slab["maximum_qty"],
                "price": slab["price"],
                "price_status": slab["price_status"],
                "supplier_id": slab["supplier_id"],
                "created_at": now_iso(),
            },
        )
    return group_slabs(group_id)


def replace_group_slabs(group_id: str, slabs: list[dict[str, Any]], product_key: str = "") -> None:
    """Admin slab editing. `slabs` items need minimum_qty / maximum_qty / price."""
    execute("DELETE FROM pricing_slabs WHERE group_id = ?", (group_id,))
    for slab in sorted(slabs, key=lambda s: int(s["minimum_qty"])):
        max_qty = slab.get("maximum_qty")
        insert(
            "pricing_slabs",
            {
                "id": new_id("SLAB", width=6, start=1),
                "group_id": group_id,
                "product_key": product_key or None,
                "minimum_qty": int(slab["minimum_qty"]),
                "maximum_qty": int(max_qty) if max_qty not in (None, "", 0) else None,
                "price": float(slab["price"]),
                "price_status": slab.get("price_status", "indicative"),
                "supplier_id": slab.get("supplier_id"),
                "created_at": now_iso(),
            },
        )


def set_supplier_confirmed(group_id: str, confirmed: bool, supplier_id: str | None = None) -> None:
    execute(
        "UPDATE pricing_slabs SET price_status = ?, supplier_id = COALESCE(?, supplier_id) "
        "WHERE group_id = ?",
        ("supplier_confirmed" if confirmed else "indicative", supplier_id, group_id),
    )
    execute(
        "UPDATE buying_groups SET supplier_price_confirmed = ?, updated_at = ? WHERE id = ?",
        (1 if confirmed else 0, now_iso(), group_id),
    )


# --------------------------------------------------------------------------- #
# calculation
# --------------------------------------------------------------------------- #
def slab_for_qty(slabs: list[dict[str, Any]], qty: float) -> dict[str, Any] | None:
    """The applicable slab for a quantity. Below the first slab we still use the
    first slab (that is the reference / single-buyer price)."""
    if not slabs:
        return None
    current = slabs[0]
    for slab in slabs:
        if qty >= slab["minimum_qty"]:
            current = slab
        else:
            break
    return current


def next_slab(slabs: list[dict[str, Any]], qty: float) -> dict[str, Any] | None:
    for slab in slabs:
        if slab["minimum_qty"] > qty:
            return slab
    return None


def calculate(slabs: list[dict[str, Any]], qty: float, customer_qty: float = 0) -> dict[str, Any]:
    """Core pricing calculation. Pure function over slabs + quantity."""
    if not slabs:
        return {
            "has_pricing": False, "quantity": qty, "reference_price": None,
            "current_price": None, "current_slab_min_qty": None,
            "next_target_qty": None, "next_price": None, "gap_to_next_price": None,
            "saving_per_unit": 0.0, "customer_saving": 0.0,
            "next_saving_per_unit": 0.0, "customer_next_saving": 0.0,
            "price_status": "indicative", "is_top_slab": True,
        }

    reference = float(slabs[0]["price"])
    current = slab_for_qty(slabs, qty) or slabs[0]
    upcoming = next_slab(slabs, qty)

    current_price = float(current["price"])
    saving_per_unit = max(0.0, reference - current_price)
    next_price = float(upcoming["price"]) if upcoming else None
    next_saving_per_unit = max(0.0, current_price - next_price) if next_price is not None else 0.0
    gap = max(0, int(upcoming["minimum_qty"]) - int(qty)) if upcoming else None

    return {
        "has_pricing": True,
        "quantity": qty,
        "reference_price": reference,
        "current_price": current_price,
        "current_slab_min_qty": int(current["minimum_qty"]),
        "current_slab_max_qty": current["maximum_qty"],
        "next_target_qty": int(upcoming["minimum_qty"]) if upcoming else None,
        "next_price": next_price,
        "gap_to_next_price": gap,
        "saving_per_unit": saving_per_unit,
        "customer_saving": saving_per_unit * customer_qty,
        "next_saving_per_unit": next_saving_per_unit,
        "customer_next_saving": next_saving_per_unit * customer_qty,
        "price_status": current.get("price_status", "indicative"),
        "is_top_slab": upcoming is None,
    }


def for_group(group: dict[str, Any], customer_qty: float = 0) -> dict[str, Any]:
    """Pricing snapshot for a group row, using its strong-intent quantity."""
    slabs = group_slabs(group["id"])
    result = calculate(slabs, float(group.get("strong_intent_qty") or 0), customer_qty)
    result["slabs"] = slabs
    result["supplier_price_confirmed"] = bool(group.get("supplier_price_confirmed"))
    if result["supplier_price_confirmed"]:
        result["price_status"] = "supplier_confirmed"
    return result


# --------------------------------------------------------------------------- #
# presentation (backend-owned strings -- the AI only echoes these)
# --------------------------------------------------------------------------- #
def price_facts(group: dict[str, Any], customer_qty: float = 0) -> dict[str, Any]:
    """A flat, render-ready fact sheet. This is the ONLY pricing information
    handed to the language model."""
    category = catalog.require(group["product_category"])
    p = for_group(group, customer_qty)
    qty = float(group.get("strong_intent_qty") or 0)

    facts: dict[str, Any] = {
        "group_code": group["code"],
        "group_label": group_label(group),
        "city": group["city"],
        "product": category.spec_description(spec_of(group)),
        "unit": category.unit,
        "group_quantity": qty,
        "group_quantity_text": category.qty_label(qty),
        "your_quantity": customer_qty,
        "your_quantity_text": category.qty_label(customer_qty) if customer_qty else "",
        "has_pricing": p["has_pricing"],
        "price_confirmed": p.get("supplier_price_confirmed", False),
    }
    if not p["has_pricing"]:
        return facts

    facts.update(
        {
            "reference_price": p["reference_price"],
            "reference_price_text": money(p["reference_price"]),
            "current_price": p["current_price"],
            "current_price_text": money(p["current_price"]),
            # The slab floor lets the UI draw progress *within* the current
            # band rather than from zero.
            "current_slab_min_qty": p["current_slab_min_qty"],
            "saving_per_unit": p["saving_per_unit"],
            "saving_per_unit_text": money(p["saving_per_unit"]),
            "your_saving": p["customer_saving"],
            "your_saving_text": money(p["customer_saving"]),
            "next_target_qty": p["next_target_qty"],
            "next_target_text": category.qty_label(p["next_target_qty"]) if p["next_target_qty"] else "",
            "next_price": p["next_price"],
            "next_price_text": money(p["next_price"]) if p["next_price"] else "",
            "gap_to_next_price": p["gap_to_next_price"],
            "gap_text": category.qty_label(p["gap_to_next_price"]) if p["gap_to_next_price"] else "",
            "next_saving_per_unit": p["next_saving_per_unit"],
            "next_saving_per_unit_text": money(p["next_saving_per_unit"]),
            "your_next_saving": p["customer_next_saving"],
            "your_next_saving_text": money(p["customer_next_saving"]),
            "is_top_slab": p["is_top_slab"],
        }
    )
    return facts


def spec_of(group: dict[str, Any]) -> dict[str, Any]:
    from ..db import loads

    return loads(group.get("product_specification"), {})


_spec = spec_of  # backwards-compatible alias


def group_label(group: dict[str, Any]) -> str:
    category = catalog.get(group["product_category"])
    spec = spec_of(group)
    product = category.spec_description(spec) if category else group["product_category"]
    return f"{group['city']} – {product}"


def slab_table(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for the 'quantity -> price' table shown in chat and admin."""
    category = catalog.require(group["product_category"])
    slabs = group_slabs(group["id"])
    qty = float(group.get("strong_intent_qty") or 0)
    active = slab_for_qty(slabs, qty)
    rows = []
    for slab in slabs:
        top = slab["maximum_qty"]
        label = f"{qty_str(slab['minimum_qty'])}–{qty_str(top)}" if top else f"{qty_str(slab['minimum_qty'])}+"
        rows.append(
            {
                "range": f"{label} {category.unit_plural if category.unit != 'kg' else 'kg'}",
                "minimum_qty": slab["minimum_qty"],
                "maximum_qty": top,
                "price": slab["price"],
                "price_text": money(slab["price"]),
                "price_status": slab["price_status"],
                "active": bool(active and slab["id"] == active["id"]),
                "unlocked": qty >= slab["minimum_qty"],
            }
        )
    return rows


def snapshot_json(group: dict[str, Any], customer_qty: float = 0) -> str:
    return dumps(price_facts(group, customer_qty))
