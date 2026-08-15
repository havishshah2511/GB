"""Customer records. There is no customer login -- the mobile number is the
identity, exactly as it will be for WhatsApp/SMS delivery."""
from __future__ import annotations

from typing import Any

from ..db import execute, insert, new_id, now_iso, query, query_one, row_to_dict
from ..utils import clean_name, normalise_mobile, token


def get(customer_id: str) -> dict[str, Any] | None:
    return row_to_dict(query_one("SELECT * FROM customers WHERE id = ?", (customer_id,)))


def by_mobile(mobile: str) -> dict[str, Any] | None:
    normalised = normalise_mobile(mobile)
    if not normalised:
        return None
    return row_to_dict(query_one("SELECT * FROM customers WHERE mobile = ?", (normalised,)))


def upsert(
    name: str | None = None,
    mobile: str | None = None,
    area: str | None = None,
    city: str | None = None,
    pincode: str | None = None,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Create or enrich a customer. Existing non-empty fields are only
    overwritten when a new value is supplied."""
    normalised = normalise_mobile(mobile)
    existing = get(customer_id) if customer_id else None
    if existing is None and normalised:
        existing = by_mobile(normalised)

    fields = {
        "name": clean_name(name) or (name.strip() if name else None),
        "mobile": normalised,
        "area": (area or "").strip() or None,
        "city": (city or "").strip() or None,
        "pincode": (pincode or "").strip() or None,
    }
    fields = {k: v for k, v in fields.items() if v}

    if existing:
        patch = {k: v for k, v in fields.items() if v and v != existing.get(k)}
        if patch:
            patch["updated_at"] = now_iso()
            sets = ", ".join(f"{k} = ?" for k in patch)
            execute(f"UPDATE customers SET {sets} WHERE id = ?", [*patch.values(), existing["id"]])
        return get(existing["id"])  # type: ignore[return-value]

    stamp = now_iso()
    record = {
        "id": new_id("CUS", width=5, start=1000),
        "name": fields.get("name"),
        "mobile": fields.get("mobile"),
        "mobile_verified": 0,
        "area": fields.get("area"),
        "city": fields.get("city"),
        "pincode": fields.get("pincode"),
        "created_at": stamp,
        "updated_at": stamp,
    }
    insert("customers", record)
    return get(record["id"])  # type: ignore[return-value]


def by_status_token(status_token: str) -> dict[str, Any] | None:
    if not status_token:
        return None
    return row_to_dict(
        query_one("SELECT * FROM customers WHERE status_token = ?", (status_token.strip(),))
    )


def ensure_status_token(customer_id: str) -> str:
    """An unguessable handle for the 'my requests' page.

    There is no customer login, so the link itself is the credential -- it must
    not be derivable from the mobile number.
    """
    customer = get(customer_id)
    if customer is None:
        raise KeyError(f"Unknown customer {customer_id}")
    existing = customer.get("status_token")
    if existing:
        return str(existing)
    value = token(24)
    execute(
        "UPDATE customers SET status_token = ?, updated_at = ? WHERE id = ?",
        (value, now_iso(), customer_id),
    )
    return value


def status_url(customer_id: str, base_url: str = "") -> str:
    from ..config import settings

    return f"{settings.base_url(base_url)}/my/{ensure_status_token(customer_id)}"


def mark_verified(customer_id: str) -> None:
    """OTP hook -- unused in the MVP flow but wired for the next iteration."""
    execute(
        "UPDATE customers SET mobile_verified = 1, updated_at = ? WHERE id = ?",
        (now_iso(), customer_id),
    )


def list_customers(search: str = "", limit: int = 100) -> list[dict[str, Any]]:
    sql = (
        "SELECT c.*, "
        "(SELECT COUNT(*) FROM purchase_intents i WHERE i.customer_id = c.id) AS intent_count, "
        "(SELECT COALESCE(SUM(i.quantity), 0) FROM purchase_intents i "
        " WHERE i.customer_id = c.id AND i.status = 'active') AS active_qty "
        "FROM customers c"
    )
    params: list[Any] = []
    if search:
        sql += " WHERE c.name LIKE ? OR c.mobile LIKE ? OR c.city LIKE ?"
        like = f"%{search}%"
        params += [like, like, like]
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in query(sql, params)]
