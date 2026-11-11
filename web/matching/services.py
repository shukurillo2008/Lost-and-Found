"""Match decision logic shared by the office UI and the Telegram bot.

Both entry points must agree on what confirming/rejecting means, so the
state transitions live here and the callers only add their own
messaging/HTTP concerns.
"""
from django.utils import timezone

OUTCOME_CONFIRMED = "confirmed"
OUTCOME_REJECTED = "rejected"
OUTCOME_NOOP = "noop"


def apply_decision(suggestion, action: str, reviewer=None):
    """Confirm or reject one ``MatchSuggestion`` and keep the report in sync.

    * ``confirm`` — only a fresh (``suggested``) row confirms; an already
      reviewed row is a no-op. The report moves ``open`` → ``matched``.
    * ``reject`` — allowed on ``suggested`` and ``confirmed`` rows (undo of
      a confirmation). Rejecting the last confirmed suggestion drops the
      report back to ``open``.

    ``reviewer`` is the staff ``User`` from the office UI; the Telegram
    path passes ``None`` because the reporter is not a staff account.
    Returns one of the ``OUTCOME_*`` constants.
    """
    report = suggestion.lost_report
    if action == "confirm" and suggestion.status != "suggested":
        return OUTCOME_NOOP
    if action == "reject" and suggestion.status == "rejected":
        return OUTCOME_NOOP

    suggestion.status = "confirmed" if action == "confirm" else "rejected"
    suggestion.reviewed_by = reviewer
    suggestion.reviewed_at = timezone.now()
    suggestion.save()
    if action == "confirm":
        if report.status == "open":
            report.status = "matched"
            report.save()
        return OUTCOME_CONFIRMED

    if report.status == "matched" and not report.match_suggestions.filter(
        status="confirmed"
    ).exists():
        report.status = "open"
        report.save()
    return OUTCOME_REJECTED
