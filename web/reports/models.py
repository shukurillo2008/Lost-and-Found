from django.db import models

from catalog.translation import auto_fill


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


class ReportInternals(models.Model):
    """Shared behaviour for Lost/Found reports (never instantiated)."""

    class Meta:
        abstract = True

    def _sync_translated_title(self) -> None:
        """Sync the reporter-language title stream from ``title`` and
        auto-translate the other two (blank) streams."""
        src = (self.reporter.language if self.reporter_id else "en") or "en"
        if src not in ("uz", "ru", "en"):
            src = "en"
        fields_map = {
            lang: (getattr(self, f"title_{lang}", "") or "")
            for lang in ("uz", "en", "ru")
        }
        fields_map[src] = self.title
        auto_fill(fields_map, source_lang=src)
        for lang, value in fields_map.items():
            setattr(self, f"title_{lang}", value)

    def title_in(self, lang: str) -> str:
        """Title shown in ``lang``; falls back to the original entry."""
        value = getattr(self, f"title_{lang}", "") or ""
        return value or self.title

    def _sync_translated_description(self) -> None:
        """Sync the reporter-language description stream from ``description``
        and auto-translate the other two (blank) streams."""
        src = (self.reporter.language if self.reporter_id else "en") or "en"
        if src not in ("uz", "ru", "en"):
            src = "en"
        fields_map = {
            lang: (getattr(self, f"description_{lang}", "") or "")
            for lang in ("uz", "en", "ru")
        }
        fields_map[src] = self.description
        auto_fill(fields_map, source_lang=src)
        for lang, value in fields_map.items():
            setattr(self, f"description_{lang}", value)

    def description_in(self, lang: str) -> str:
        """Description shown in ``lang``; falls back to the original entry."""
        value = getattr(self, f"description_{lang}", "") or ""
        return value or self.description


class LostReport(ReportInternals):
    """A user's claim that they lost an item."""

    reporter = models.ForeignKey(
        "bot_app.TelegramUser", on_delete=models.PROTECT, related_name="lost_reports"
    )
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="lost_reports"
    )
    title = models.CharField(max_length=120)
    title_uz = models.CharField(max_length=120, blank=True)
    title_en = models.CharField(max_length=120, blank=True)
    title_ru = models.CharField(max_length=120, blank=True)
    description = models.TextField()
    description_uz = models.TextField(blank=True)
    description_en = models.TextField(blank=True)
    description_ru = models.TextField(blank=True)
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

    def save(self, *args, **kwargs):
        self._sync_translated_title()
        self._sync_translated_description()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[LOST {self.pk}] {self.title} ({self.status})"


class FoundReport(ReportInternals):
    """A user's claim that they found an item."""

    reporter = models.ForeignKey(
        "bot_app.TelegramUser", on_delete=models.PROTECT, related_name="found_reports"
    )
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="found_reports"
    )
    title = models.CharField(max_length=120)
    title_uz = models.CharField(max_length=120, blank=True)
    title_en = models.CharField(max_length=120, blank=True)
    title_ru = models.CharField(max_length=120, blank=True)
    description = models.TextField()
    description_uz = models.TextField(blank=True)
    description_en = models.TextField(blank=True)
    description_ru = models.TextField(blank=True)
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

    def save(self, *args, **kwargs):
        self._sync_translated_title()
        self._sync_translated_description()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[FOUND {self.pk}] {self.title} ({self.status})"
