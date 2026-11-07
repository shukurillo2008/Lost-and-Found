"""Background worker service entrypoint.

Milestone 7: the worker is no longer a heartbeat stub. Every
``WORKER_INTERVAL_SECONDS`` (default 300) it runs two preserving cycles:

1. ``run_disposal_cycle`` — items still ``in_storage`` whose
   ``retention_until`` has passed are flipped to ``disposed`` and the
   transition is written to ``ItemStatusLog`` (``staff`` stays NULL for
   background actions, ``note`` explains the flip).
2. ``run_matching_cycle`` — every ``open`` lost report is scored against
   every ``in_storage`` item with the shared matching engine; pairs
   scoring above ``MIN_SYSTEM_SCORE`` become ``MatchSuggestion`` rows
   with ``created_by="system"``. Staff confirm/reject them exactly like
   user and staff suggestions (no auto-confirm).
"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent    # /app
sys.path.insert(0, str(BASE_DIR / "web"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.utils import timezone  # noqa: E402

from matching.engine import score_breakdown, score_from_breakdown, strong_enough  # noqa: E402
from matching.models import MatchSuggestion  # noqa: E402
from reports.models import LostReport  # noqa: E402
from storage.models import ItemStatusLog, StoredItem  # noqa: E402

logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

HEARTBEAT_SECONDS = 30


def run_disposal_cycle() -> dict:
    """Flip overdue storage items to ``disposed`` and audit the transition.

    An item is overdue when its ``retention_until`` date has fully passed
    (deadline day itself is still bookable for a handover).
    """
    today = timezone.localdate()
    overdue = StoredItem.objects.filter(
        status="in_storage", retention_until__lt=today
    ).select_related("category")
    stats = {"disposed": 0}
    for item in overdue:
        old_status = item.status
        item.status = "disposed"
        item.save(update_fields=["status"])
        ItemStatusLog.objects.create(
            item=item,
            old_status=old_status,
            new_status="disposed",
            staff=None,
            note="Retention period ended - disposed automatically by the worker.",
        )
        stats["disposed"] += 1
        logger.info("disposed item %s (%s)", item.shelf_code, item.title)
    return stats


def run_matching_cycle() -> dict:
    """Score open reports against storage items; keep strong pairs only.

    Skips pairs that already have a suggestion (unique constraint) and
    pairs below the system threshold. A suggestion is never confirmed by
    itself — staff review it on the report page or the match queue.
    """
    open_reports = (
        LostReport.objects.filter(status="open")
        .select_related("category", "color", "location", "reporter")
    )
    items = (
        StoredItem.objects.filter(status="in_storage")
        .select_related("category", "color", "found_report")
    )
    stats = {"scored": 0, "suggestions": 0}
    for lost in open_reports:
        existing_ids = set(
            lost.match_suggestions.values_list("stored_item_id", flat=True)
        )
        for item in items:
            if item.pk in existing_ids:
                continue
            stats["scored"] += 1
            breakdown = score_breakdown(lost, item)
            score = score_from_breakdown(breakdown)
            if not strong_enough(score):
                continue
            MatchSuggestion.objects.create(
                lost_report=lost,
                stored_item=item,
                created_by="system",
                score=score,
                score_breakdown={"source": "worker", **breakdown},
                status="suggested",
            )
            stats["suggestions"] += 1
            logger.info(
                "system suggestion: report #%s × item #%s (score %s)",
                lost.pk, item.pk, score,
            )
    return stats


def run_work_cycle() -> dict:
    """One worker pass: disposal first (frees nothing to match), then matching."""
    stats = run_disposal_cycle()
    stats.update(run_matching_cycle())
    logger.info("work cycle finished: %s", stats)
    return stats


async def run():
    interval = int(os.environ.get("WORKER_INTERVAL_SECONDS", "300") or 300)
    logger.info(
        "Worker service is running; heartbeat every %ss, work cycle every %ss.",
        HEARTBEAT_SECONDS, interval,
    )
    last_cycle = 0.0
    while True:
        now = time.monotonic()
        if now - last_cycle >= interval:
            try:
                # Blocking ORM calls in a cron-style worker are fine at this
                # scale; asyncio only drives the sleep loop here.
                run_work_cycle()
                last_cycle = now
            except Exception:
                logger.exception("work cycle failed; retrying on the next tick")
        logger.info("worker heartbeat: alive")
        await asyncio.sleep(HEARTBEAT_SECONDS)


def main():
    logger.info("Starting Campus Lost & Found worker service (M7 cycles active).")
    asyncio.run(run())


if __name__ == "__main__":
    main()
