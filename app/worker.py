"""Background maintenance loop (spec sections 18, 20, 25).

Everything here is also reachable over HTTP, so the loop can be disabled and
driven by an external scheduler (cron, Cloud Scheduler, a queue worker) instead.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import settings
from .db import close_conn
from .services import groups, intents, notifications

log = logging.getLogger("groupbuy.worker")


def run_once(base_url: str = "") -> dict[str, Any]:
    """One maintenance pass. Safe to call concurrently -- every step is
    idempotent and notification dedupe keys prevent repeats."""
    # Consolidate first: pooling two groups changes quantities and prices, and
    # the members of the absorbed group should hear about that in this same
    # pass rather than a minute later.
    consolidated = groups.consolidate()
    expired = intents.expire_due()
    reminders = notifications.send_expiry_reminders(base_url)
    dispatched = notifications.dispatch()
    result = {
        "groups_merged": consolidated["groups_merged"],
        "intents_expired": expired["expired"],
        "groups_recalculated": expired["groups_recalculated"],
        "expiry_reminders_queued": reminders,
        "notifications_sent": dispatched["sent"],
        "notifications_failed": dispatched["failed"],
    }
    for entry in consolidated["merged"]:
        log.info(
            "merged %s into %s (%s) -- %g units pooled",
            entry["source"], entry["target"], entry["reason"], entry["quantity_moved"],
        )
    return result


def sweep_groups() -> int:
    """Re-check every open group for near-target / progress milestones. Cheap
    because notifications are deduped; run it less often than run_once()."""
    outcomes = groups.recalculate_all(notify=True)
    return sum(len(o["notifications"]) for o in outcomes)


async def loop(base_url: str = "") -> None:
    interval = max(10, settings.WORKER_INTERVAL_SECONDS)
    log.info("background worker started (every %ss)", interval)
    ticks = 0
    try:
        while True:
            try:
                result = run_once(base_url)
                ticks += 1
                # Full group sweep every ~10 ticks.
                if ticks % 10 == 0:
                    result["milestone_notifications"] = sweep_groups()
                if any(v for k, v in result.items() if k != "notifications_failed"):
                    log.info("worker tick: %s", result)
            except Exception:
                log.exception("worker tick failed")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("background worker stopped")
        raise
    finally:
        close_conn()
