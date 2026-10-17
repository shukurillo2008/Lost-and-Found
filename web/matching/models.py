from django.conf import settings
from django.db import models


class MatchSuggestionQuerySet(models.QuerySet):
    def with_common_related(self):
        return self.select_related(
            "lost_report", "lost_report__reporter", "lost_report__category",
            "stored_item__category", "found_report", "found_report__reporter",
            "reviewed_by",
        )

    def by_status(self, status):
        return self.filter(status=status)

    def pending(self):
        return self.filter(status="suggested")


class HandoverQuerySet(models.QuerySet):
    def with_common_related(self):
        return self.select_related("stored_item", "lost_report", "staff")


class MatchSuggestion(models.Model):
    """A candidate pairing of a lost report with a found item.

    Suggestions come from the system worker, from staff, or from a user
    pressing "this is mine" on a found-item card.
    """

    CREATED_BY_CHOICES = [("system", "System"), ("staff", "Staff"), ("user", "User")]

    lost_report = models.ForeignKey(
        "reports.LostReport", on_delete=models.CASCADE, related_name="match_suggestions"
    )
    stored_item = models.ForeignKey(
        "storage.StoredItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="match_suggestions",
    )
    found_report = models.ForeignKey(
        "reports.FoundReport", on_delete=models.CASCADE, null=True, blank=True,
        related_name="match_suggestions",
    )
    score = models.PositiveIntegerField(default=0)
    score_breakdown = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=8, choices=CREATED_BY_CHOICES, default="system")
    status = models.CharField(
        max_length=16,
        choices=(("suggested", "Suggested"), ("confirmed", "Confirmed"), ("rejected", "Rejected")),
        default="suggested",
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_matches",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MatchSuggestionQuerySet.as_manager()

    class Meta:
        ordering = ["-score", "-created_at"]
        indexes = [
            models.Index(
                fields=["status", "-score", "-created_at"],
                name="match_status_score_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=["lost_report", "stored_item"], name="unique_lost_item_suggestion"),
            models.CheckConstraint(
                condition=models.Q(stored_item__isnull=False) | models.Q(found_report__isnull=False),
                name="suggestion_needs_a_source",
            ),
        ]

    def __str__(self):
        return f"Lost#{self.lost_report_id} × Item#{self.stored_item_id or '—'} (score {self.score}, {self.status})"


class Handover(models.Model):
    """Confidential proof-of-return record created when an item leaves storage."""

    stored_item = models.OneToOneField(
        "storage.StoredItem", on_delete=models.CASCADE, related_name="handover"
    )
    lost_report = models.ForeignKey(
        "reports.LostReport", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="handovers",
    )
    receiver_name = models.CharField(max_length=128)
    receiver_id_last4 = models.CharField(max_length=4)
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="handovers_registered"
    )
    handed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    objects = HandoverQuerySet.as_manager()

    class Meta:
        ordering = ["-handed_at"]

    def __str__(self):
        return f"Handover of {self.stored_item.title} to {self.receiver_name}"
