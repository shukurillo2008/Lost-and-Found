"""Background worker service entrypoint.

Every ``WORKER_MATCH_INTERVAL_MINUTES`` (default 10; the legacy
``WORKER_INTERVAL_SECONDS`` override still wins when set) the worker runs
three preserving cycles:

1. ``run_retention_cycle`` — counts in-storage items expiring within 7
   days (digest feed) and items past their deadline ("ready for
   disposal"). It NEVER flips a status: disposal is a staff decision
   (course §4.4).
2. ``run_expiry_cycle`` — open lost reports older than 90 days become
   ``expired`` and the reporter gets a one-tap reopen button in the bot.
3. ``run_matching_cycle`` — every ``open`` lost report is scored against
   every ``in_storage`` item with the shared matching engine; pairs
   scoring above ``MIN_SYSTEM_SCORE`` become ``MatchSuggestion`` rows
   with ``created_by="system"`` and the reporter is notified. Staff
   confirm/reject them exactly like user and staff suggestions (no
   auto-confirm).

A fourth job runs on every heartbeat: ``send_daily_digest`` posts the
office digest to ``OFFICE_GROUP_ID`` once per local day at
``WORKER_DIGEST_HOUR`` (default 09:00 Asia/Tashkent). ``DigestRun`` is the
per-date idempotency guard, so restarts cannot double-send.
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

from bot_app.digest import digest_hour, send_daily_digest  # noqa: E402
from bot_app.notifications import notify_expired, notify_suggestion  # noqa: E402
from matching.engine import score_breakdown, score_from_breakdown, strong_enough  # noqa: E402
from matching.models import MatchSuggestion  # noqa: E402
from reports.models import LostReport  # noqa: E402
from storage.models import StoredItem  # noqa: E402
from storage.retention import (  # noqa: E402
    EXPIRING_WINDOW_DAYS,
    expired_lost_reports,
    retention_summary,
)

logger = logging.getLogger("worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

HEARTBEAT_SECONDS = 30


def run_retention_cycle() -> dict:
    """Flag retention states for the daily digest — never flips a status.

    Items past ``retention_until`` stay ``in_storage`` and are only
    reported as "ready for disposal"; a staff member performs the actual
    disposal from the item page (course §4.4: status changes only by
    staff, never automatically).
    """
    summary = retention_summary()
    logger.info(
        "retention flags: %s item(s) expiring within %s days, %s ready for disposal",
        summary["expiring"], EXPIRING_WINDOW_DAYS, summary["ready_for_disposal"],
    )
    return summary


def run_expiry_cycle() -> dict:
    """Close open lost reports older than 90 days and notify the reporter.

    The status flip is a queryset update (skips the auto-translate save
    hook). ``reopened_at`` is untouched here; the bot writes it when the
    reporter reopens the report, which restarts the 90-day clock.
    """
    stats = {"expired": 0, "expired_notified": 0}
    for report in expired_lost_reports().select_related("reporter"):
        updated = LostReport.objects.filter(pk=report.pk, status="open").update(
            status="expired"
        )
        if not updated:
            continue
        report.status = "expired"
        stats["expired"] += 1
        if notify_expired(report):
            stats["expired_notified"] += 1
        logger.info("expired lost report #%s (%s)", report.pk, report.title)
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
    stats = {"scored": 0, "suggestions": 0, "notified": 0}
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
            suggestion = MatchSuggestion.objects.create(
                lost_report=lost,
                stored_item=item,
                created_by="system",
                score=score,
                score_breakdown={"source": "worker", **breakdown},
                status="suggested",
            )
            stats["suggestions"] += 1
            if notify_suggestion(suggestion):
                stats["notified"] += 1
            logger.info(
                "system suggestion: report #%s × item #%s (score %s)",
                lost.pk, item.pk, score,
            )
    return stats


def run_work_cycle() -> dict:
    """One worker pass: retention flags, report expiry, then matching."""
    stats = run_retention_cycle()
    stats.update(run_expiry_cycle())
    stats.update(run_matching_cycle())
    logger.info("work cycle finished: %s", stats)
    return stats


def _match_interval_seconds() -> int:
    """Match-cycle period: legacy seconds override, else minutes (default 10)."""
    raw = os.environ.get("WORKER_INTERVAL_SECONDS")
    if raw:
        try:
            return max(30, int(raw))
        except (TypeError, ValueError):
            logger.warning("invalid WORKER_INTERVAL_SECONDS=%r; falling back", raw)
    try:
        minutes = int(os.environ.get("WORKER_MATCH_INTERVAL_MINUTES", "10") or 10)
    except (TypeError, ValueError):
        minutes = 10
    return max(60, minutes * 60)


async def run():
    interval = _match_interval_seconds()
    logger.info(
        "Worker service is running; heartbeat every %ss, work cycle every %ss "
        "(%s min), digest hour %s local.",
        HEARTBEAT_SECONDS, interval, round(interval / 60), digest_hour(),
    )
    last_cycle = time.monotonic()   # first pass after one full interval
    while True:
        now = time.monotonic()
        if now - last_cycle >= interval:
            try:
                # Django forbids synchronous ORM calls inside a running event
                # loop, so hand the whole cycle to a worker thread. asyncio
                # only drives the sleep loop here.
                await asyncio.to_thread(run_work_cycle)
                last_cycle = now
            except Exception:
                logger.exception("work cycle failed; retrying on the next tick")
        try:
            # Idempotent per local date; cheap no-op before the digest hour.
            digest = await asyncio.to_thread(send_daily_digest)
            if digest["status"] == "sent":
                logger.info("daily digest delivered: %s", digest["counts"])
        except Exception:
            logger.exception("daily digest failed; retrying on the next tick")
        logger.info("worker heartbeat: alive")
        await asyncio.sleep(HEARTBEAT_SECONDS)


def main():
    logger.info("Starting Campus Lost & Found worker service (M7 cycles active).")
    asyncio.run(run())


if __name__ == "__main__":
    main()
