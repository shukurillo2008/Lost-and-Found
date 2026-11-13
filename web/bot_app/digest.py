"""Daily office digest sent to the staff Telegram group.

Course §4.4 asks for a daily digest at 09:00 Asia/Tashkent. The digest
summarises the work the office must do today:

* items whose ``retention_until`` falls within the next 7 days;
* items already past the deadline ("ready for disposal" — staff-only);
* open lost reports and pending match suggestions;
* today's received / returned / disposed totals.

Sending is **idempotent per local date**: ``DigestRun.sent_on`` is unique,
so a worker restart or a duplicate tick cannot send the same day twice.
The worker calls :func:`send_daily_digest` every heartbeat; the function
returns a small status dict and never raises.

The digest is a Telegram message, not office-UI text, so its strings live
here (like ``notifications.py``) instead of gettext.
"""
import logging
import os
from datetime import timedelta
from html import escape

from django.conf import settings
from django.utils import timezone

from matching.models import Handover, MatchSuggestion
from reports.models import LostReport
from storage.models import ItemStatusLog, StoredItem
from storage.retention import expiring_soon, ready_for_disposal

from . import telegram_api
from .models import DigestRun

logger = logging.getLogger("bot_digest")

DEFAULT_DIGEST_HOUR = 9
DEFAULT_RETRY_MINUTES = 10
MAX_ATTEMPTS = 5
MAX_LISTED = 10


def digest_hour() -> int:
    """Local hour (0–23) at which the digest becomes due (env, default 9)."""
    raw = os.environ.get("WORKER_DIGEST_HOUR", str(DEFAULT_DIGEST_HOUR))
    try:
        hour = int(raw)
    except (TypeError, ValueError):
        hour = DEFAULT_DIGEST_HOUR
    return min(23, max(0, hour))


def retry_cooldown_minutes() -> int:
    """Minutes to wait before retrying a failed send (env, default 10)."""
    raw = os.environ.get("DIGEST_RETRY_MINUTES", str(DEFAULT_RETRY_MINUTES))
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = DEFAULT_RETRY_MINUTES
    return max(0, minutes)


def _office_chat_id():
    """Return the office group id as int, or ``None`` when unset/invalid."""
    raw = (getattr(settings, "OFFICE_GROUP_ID", "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("OFFICE_GROUP_ID is not a numeric chat id: %r", raw)
        return None


def _item_line(item) -> str:
    return (
        f"• <code>{escape(item.shelf_code)}</code> — {escape(item.title)} "
        f"({item.retention_until.strftime('%d.%m.%Y')})"
    )


def build_digest(now=None) -> tuple[str, dict]:
    """Return ``(html_text, counts)`` for the office group.

    ``now`` is an aware datetime; defaults to the current local time. It is
    converted with ``timezone.localtime`` so the date and the "today"
    counters always follow ``settings.TIME_ZONE`` (Asia/Tashkent), never
    the container's OS clock.
    """
    now = timezone.localtime(now) if now is not None else timezone.localtime()
    today = now.date()

    expiring_qs = expiring_soon().select_related("category").order_by(
        "retention_until", "shelf_code"
    )
    ready_qs = ready_for_disposal().select_related("category").order_by(
        "retention_until", "shelf_code"
    )
    expiring_count = expiring_qs.count()
    ready_count = ready_qs.count()
    expiring = list(expiring_qs[:MAX_LISTED])
    ready = list(ready_qs[:MAX_LISTED])

    counts = {
        "in_storage": StoredItem.objects.filter(status="in_storage").count(),
        "expiring": expiring_count,
        "ready_for_disposal": ready_count,
        "open_reports": LostReport.objects.filter(status="open").count(),
        "pending_matches": MatchSuggestion.objects.filter(status="suggested").count(),
        "received_today": StoredItem.objects.filter(received_at__date=today).count(),
        "returned_today": Handover.objects.filter(handed_at__date=today).count(),
        "disposed_today": ItemStatusLog.objects.filter(
            new_status="disposed", created_at__date=today
        ).count(),
    }

    lines = [
        f"📋 <b>Kunlik hisobot</b> — {today.strftime('%d.%m.%Y')}",
        "",
        f"📦 Omborda: <b>{counts['in_storage']}</b> ta buyum",
        f"⏳ 7 kun ichida muddati tugaydi: <b>{counts['expiring']}</b>",
        f"🗑 Utilizatsiyaga tayyor: <b>{counts['ready_for_disposal']}</b>",
        f"📄 Ochiq yo'qotish arizalari: <b>{counts['open_reports']}</b>",
        f"🔎 Ko'rib chiqilishi kerak mosliklar: <b>{counts['pending_matches']}</b>",
        "",
        f"📥 Bugun qabul qilindi: {counts['received_today']}",
        f"📤 Bugun qaytarildi: {counts['returned_today']}",
        f"♻️ Bugun utilizatsiya qilindi: {counts['disposed_today']}",
    ]

    if expiring:
        lines += ["", "⏳ <b>Muddati yaqin:</b>"]
        lines += [_item_line(item) for item in expiring]
        if expiring_count > len(expiring):
            lines.append(f"… yana {expiring_count - len(expiring)} ta")

    if ready:
        lines += ["", "🗑 <b>Utilizatsiyaga tayyor:</b>"]
        lines += [_item_line(item) for item in ready]
        if ready_count > len(ready):
            lines.append(f"… yana {ready_count - len(ready)} ta")

    return "\n".join(lines), counts


def send_daily_digest(now=None, force: bool = False) -> dict:
    """Send today's digest once, at/after ``WORKER_DIGEST_HOUR`` local time.

    Statuses:
    ``sent`` / ``before_hour`` / ``disabled`` / ``already_sent`` /
    ``retry_later`` / ``gave_up`` / ``failed``.

    A failed send keeps the row and increments ``attempts``; the next
    attempt is allowed after ``DIGEST_RETRY_MINUTES`` (default 10) and the
    digest gives up for the day after ``MAX_ATTEMPTS``. This stops a bad
    chat id from hammering the Bot API every heartbeat.

    ``force`` only bypasses the hour gate (manual/testing); the per-date
    uniqueness and the retry policy still apply.
    """
    now = timezone.localtime(now) if now is not None else timezone.localtime()
    if not force and now.hour < digest_hour():
        return {"status": "before_hour", "hour": digest_hour()}

    chat_id = _office_chat_id()
    if chat_id is None or not telegram_api.is_enabled():
        logger.debug("daily digest skipped: bot token or office group is missing")
        return {"status": "disabled"}

    today = now.date()
    run, created = DigestRun.objects.get_or_create(sent_on=today)
    if not created:
        if run.message_id:
            return {"status": "already_sent", "sent_on": today.isoformat()}
        if run.attempts >= MAX_ATTEMPTS:
            return {
                "status": "gave_up",
                "sent_on": today.isoformat(),
                "attempts": run.attempts,
            }
        if run.last_attempt_at is not None:
            cooldown = timedelta(minutes=retry_cooldown_minutes())
            if now - run.last_attempt_at < cooldown:
                return {
                    "status": "retry_later",
                    "sent_on": today.isoformat(),
                    "attempts": run.attempts,
                }

    run.attempts += 1
    run.last_attempt_at = now
    run.save(update_fields=["attempts", "last_attempt_at"])

    text, counts = build_digest(now)
    try:
        message = telegram_api.send_message(chat_id, text)
    except Exception:  # never break the worker loop
        logger.exception("daily digest send raised")
        message = None

    if not message:
        logger.warning(
            "daily digest send failed (attempt %s/%s); retrying later",
            run.attempts, MAX_ATTEMPTS,
        )
        return {"status": "failed", "attempts": run.attempts, "counts": counts}

    run.counts = counts
    run.message_id = message.get("message_id") if isinstance(message, dict) else None
    run.save(update_fields=["counts", "message_id"])
    logger.info("daily digest sent to %s: %s", chat_id, counts)
    return {
        "status": "sent",
        "sent_on": today.isoformat(),
        "counts": counts,
        "message_id": run.message_id,
        "attempts": run.attempts,
    }
