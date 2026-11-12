"""Retention policy — one source of truth for worker, digest and dashboard.

Two rules from the course spec (§4.4):

* storage items whose ``retention_until`` is within the next 7 days are
  **expiring** and go into the daily digest;
* items past ``retention_until`` are **ready for disposal** — but the
  status is changed ONLY by staff, never automatically by the worker;
* open lost reports older than 90 days are **expired** (reporter gets a
  one-tap reopen button in the bot).

Everything here is derived state (no flag column): the worker logs the
counts, the digest queries the same querysets, and the dashboard buckets
already match these definitions.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from reports.models import LostReport

from .models import StoredItem

EXPIRING_WINDOW_DAYS = 7
LOST_REPORT_EXPIRY_DAYS = 90


def expiring_soon(queryset=None):
    """In-storage items whose deadline falls in [today, today+7]."""
    items = queryset if queryset is not None else StoredItem.objects.all()
    today = timezone.localdate()
    return items.filter(
        status="in_storage",
        retention_until__gte=today,
        retention_until__lte=today + timedelta(days=EXPIRING_WINDOW_DAYS),
    )


def ready_for_disposal(queryset=None):
    """In-storage items whose deadline has fully passed (deadline day is still valid)."""
    items = queryset if queryset is not None else StoredItem.objects.all()
    return items.filter(
        status="in_storage",
        retention_until__lt=timezone.localdate(),
    )


def retention_summary() -> dict:
    """Counts used by the worker log and the daily digest."""
    return {
        "expiring": expiring_soon().count(),
        "ready_for_disposal": ready_for_disposal().count(),
    }


def expired_lost_reports(queryset=None):
    """Open reports older than 90 days whose expiry clock has not been reset.

    The clock starts at ``date_lost``; reopening from the bot writes
    ``reopened_at`` so the same report is not closed again on the next
    worker pass.
    """
    reports = queryset if queryset is not None else LostReport.objects.all()
    cutoff = timezone.localdate() - timedelta(days=LOST_REPORT_EXPIRY_DAYS)
    return reports.filter(status="open").filter(
        Q(date_lost__lt=cutoff)
        & (Q(reopened_at__isnull=True) | Q(reopened_at__date__lt=cutoff))
    )
