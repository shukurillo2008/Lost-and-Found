"""Match decision logic shared by the office UI and the Telegram bot.

Both entry points must agree on what confirming/rejecting means, so the
state transitions live here and the callers only add their own
messaging/HTTP concerns.
"""
from django.db import transaction
from django.utils import timezone

from storage.models import StoredItem

OUTCOME_CONFIRMED = "confirmed"
OUTCOME_REJECTED = "rejected"
OUTCOME_NOOP = "noop"
OUTCOME_REPORT_CLOSED = "report_closed"
OUTCOME_ITEM_UNAVAILABLE = "item_unavailable"
OUTCOME_SOURCE_UNAVAILABLE = "source_unavailable"

CLOSED_REPORT_STATUSES = ("returned", "cancelled", "expired")


def suggestion_sources(lost_report) -> tuple[set, set]:
    """Stored-item ids and found-report ids already covered by suggestions.

    The worker uses both sets to stay idempotent. A suggestion made from the
    bot's "this is mine" button points only at the found report; when that
    report is later received into storage, the suggestion is relinked to the
    new ``StoredItem``. Without tracking found-report ids the worker would
    score the same physical pair again and create a duplicate row.
    """
    item_ids: set = set()
    found_ids: set = set()
    for item_id, found_id in lost_report.match_suggestions.values_list(
        "stored_item_id", "found_report_id"
    ):
        if item_id is not None:
            item_ids.add(item_id)
        if found_id is not None:
            found_ids.add(found_id)
    return item_ids, found_ids


def apply_decision(suggestion, action: str, reviewer=None):
    """Confirm or reject one ``MatchSuggestion`` and keep the report in sync.

    * Decisions are refused once the lost report is ``returned``,
      ``cancelled`` or ``expired`` — the history must stay stable.
    * ``confirm`` — only a fresh (``suggested``) row confirms; the stored
      item must still be in storage (or the found-report source still
      open/registered). Confirming one suggestion auto-rejects every other
      pending/confirmed suggestion for the same lost report, so a report can
      never end up with two confirmed matches. The report moves
      ``open`` → ``matched``.
    * ``reject`` — allowed on ``suggested`` and ``confirmed`` rows (undo of
      a confirmation). Rejecting the last confirmed suggestion drops the
      report back to ``open``.

    ``reviewer`` is the staff ``User`` from the office UI; the Telegram
    path passes ``None`` because the reporter is not a staff account.
    Returns one of the ``OUTCOME_*`` constants.
    """
    report = suggestion.lost_report
    if report.status in CLOSED_REPORT_STATUSES:
        return OUTCOME_REPORT_CLOSED

    if action == "confirm":
        if suggestion.status != "suggested":
            return OUTCOME_NOOP
        item = suggestion.stored_item
        resolved_item = None
        if item is None and suggestion.found_report_id:
            # A "this is mine" suggestion targets the found report only. If
            # the finder already handed the item in, resolve the physical
            # item so the handover can find this confirmed claim.
            linked = StoredItem.objects.filter(
                found_report_id=suggestion.found_report_id
            )
            resolved_item = linked.filter(status="in_storage").order_by("pk").first()
            if resolved_item is None and linked.exists():
                return OUTCOME_ITEM_UNAVAILABLE
            item = resolved_item
        if item is not None and item.status != "in_storage":
            return OUTCOME_ITEM_UNAVAILABLE
        found = suggestion.found_report
        if item is None and found is not None and found.status not in ("open", "registered"):
            return OUTCOME_SOURCE_UNAVAILABLE

        now = timezone.now()
        with transaction.atomic():
            # One confirmed suggestion per lost report: close every competing
            # pending or confirmed row in the same transaction as the confirm.
            report.match_suggestions.exclude(pk=suggestion.pk).filter(
                status__in=("suggested", "confirmed")
            ).update(status="rejected", reviewed_at=now, reviewed_by=reviewer)
            if resolved_item is not None:
                # Rejected rows with the same pair would violate
                # ``unique_lost_item_suggestion`` once the FK is attached.
                report.match_suggestions.filter(
                    stored_item=resolved_item
                ).exclude(pk=suggestion.pk).delete()
                suggestion.stored_item = resolved_item
            suggestion.status = "confirmed"
            suggestion.reviewed_by = reviewer
            suggestion.reviewed_at = now
            suggestion.save()
            if report.status == "open":
                report.status = "matched"
                report.save()
        return OUTCOME_CONFIRMED

    if action == "reject":
        if suggestion.status == "rejected":
            return OUTCOME_NOOP
        now = timezone.now()
        with transaction.atomic():
            suggestion.status = "rejected"
            suggestion.reviewed_by = reviewer
            suggestion.reviewed_at = now
            suggestion.save()
            if report.status == "matched" and not report.match_suggestions.filter(
                status="confirmed"
            ).exists():
                report.status = "open"
                report.save()
        return OUTCOME_REJECTED

    return OUTCOME_NOOP
