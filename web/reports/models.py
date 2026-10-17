from django.db import models


class ReportQuerySet(models.QuerySet):
    """Optimized queryset shared by lost and found reports."""

    def by_status(self, status):
        return self.filter(status=status)

    def with_common_related(self):
        return self.select_related("category", "color", "reporter", "location")


class LostReportQuerySet(ReportQuerySet):
    pass


class FoundReportQuerySet(ReportQuerySet):
    pass


STATUS_CHOICES_LOST = (
    ("open", "Open"),
    ("matched", "Matched"),
    ("returned", "Returned"),
    ("expired", "Expired"),
    ("cancelled", "Cancelled"),
)

STATUS_CHOICES_FOUND = (
    ("open", "Open"),
    ("registered", "Registered"),
    ("returned", "Returned"),
    ("cancelled", "Cancelled"),
)

CUSTODY_CHOICES = (
    ("handed_to_office", "Handed to office"),
    ("kept_by_finder", "Kept by finder"),
)


class LostReport(models.Model):
    """A user's claim that they lost an item."""

    reporter = models.ForeignKey(
        "bot_app.TelegramUser", on_delete=models.PROTECT, related_name="lost_reports"
    )
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="lost_reports"
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    color = models.ForeignKey(
        "catalog.Color", on_delete=models.PROTECT, related_name="lost_reports"
    )
    brand_marks = models.CharField(max_length=255, blank=True)
    location = models.ForeignKey(
        "catalog.Location", on_delete=models.SET_NULL, null=True, blank=True, related_name="lost_reports"
    )
    date_lost = models.DateField()
    photo_file_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES_LOST, default="open", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LostReportQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "date_lost"], name="lost_status_date_idx"),
            models.Index(fields=["category", "status"], name="lost_cat_status_idx"),
            models.Index(fields=["reporter", "status"], name="lost_reporter_status_idx"),
        ]

    def __str__(self):
        return f"[LOST {self.pk}] {self.title} ({self.status})"


class FoundReport(models.Model):
    """A user's claim that they found an item."""

    reporter = models.ForeignKey(
        "bot_app.TelegramUser", on_delete=models.PROTECT, related_name="found_reports"
    )
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="found_reports"
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    color = models.ForeignKey(
        "catalog.Color", on_delete=models.PROTECT, related_name="found_reports"
    )
    location = models.ForeignKey(
        "catalog.Location", on_delete=models.PROTECT, related_name="found_reports"
    )
    date_found = models.DateField()
    photo_file_id = models.CharField(max_length=255, blank=True)
    custody = models.CharField(max_length=24, choices=CUSTODY_CHOICES)
    finder_contact_allowed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES_FOUND, default="open", db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FoundReportQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "date_found"], name="found_status_date_idx"),
            models.Index(fields=["reporter", "status"], name="found_reporter_status_idx"),
            models.Index(fields=["category", "status"], name="found_cat_status_idx"),
        ]

    def __str__(self):
        return f"[FOUND {self.pk}] {self.title} ({self.status})"
