#!/usr/bin/env python
"""Delete every customer record so the back office starts from nothing.

    python wipe.py            # asks for confirmation, then wipes
    python wipe.py --yes      # no prompt (for scripts)
    python wipe.py --keep-pricing

Removes customers, purchase intents, buying groups, referrals, conversations
and notifications. Pricing slab templates are rebuilt afterwards, so the app
can price a brand new group immediately.

Stop the server before running this.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings           # noqa: E402
from app.db import execute, get_conn, init_db, query_one  # noqa: E402
from app.services import pricing          # noqa: E402

#: Child rows first -- foreign keys are enforced.
TABLES = (
    "referral_events",
    "referrals",
    "notifications",
    "purchase_intents",
    "conversations",
    "pricing_slabs",
    "buying_groups",
    "customers",
    "admin_audit",
    "sequences",
)


def counts() -> dict[str, int]:
    result = {}
    for table in ("customers", "purchase_intents", "buying_groups", "notifications"):
        row = query_one(f"SELECT COUNT(*) AS n FROM {table}")
        result[table] = int(row["n"]) if row else 0
    return result


def wipe(keep_pricing: bool = False) -> None:
    """Same code path as the back office's Reset action, so both behave alike."""
    from app.services import groups

    init_db()
    groups.reset_all()
    # VACUUM cannot run inside a transaction, so it bypasses the helper.
    get_conn().execute("VACUUM")


def main() -> int:
    args = set(sys.argv[1:])
    keep_pricing = "--keep-pricing" in args

    init_db()
    before = counts()
    total = sum(before.values())
    print(f"Database: {settings.DB_PATH}")
    for table, n in before.items():
        print(f"  {table:<20} {n}")

    if total == 0:
        print("\nAlready empty — nothing to do.")
        return 0

    if "--yes" not in args and "-y" not in args:
        print(f"\nThis permanently deletes {total} rows. There is no undo.")
        try:
            if input("Type 'wipe' to confirm: ").strip().lower() != "wipe":
                print("Cancelled — nothing was deleted.")
                return 1
        except EOFError:
            print("Cancelled — no console to confirm on. Re-run with --yes.")
            return 1

    wipe(keep_pricing)
    print("\nWiped. Now:")
    for table, n in counts().items():
        print(f"  {table:<20} {n}")
    print("\nPricing slab templates rebuilt." if not keep_pricing else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
