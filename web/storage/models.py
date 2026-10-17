from django.db import models
from django.conf import settings
from django.utils import timezone

from datetime import timedelta

STORED_STATUSES = (
    ("in_storage", "In storage"),
    ("returned", "Returned"),
    ("disposed", "Disposed"),
    ("transferred", "Transferred"),
)


class StoredItemQuerySet(models.QuerySet):
    HOT_RELATED = ("category", "color", "received_by", "found_report__reporter")

    def by_status(self, status):
        return self.filter(status=status)

    def active(self):
        return self.filter(status="in_storage")

    def with_common_related(self):
        return self.select_related(*self.HOT_RELATED)


class ItemStatusLogQuerySet(models.QuerySet):
    def with_common_related(self):
        return self.select_related("item", "staff")


class StoredItem(models.Model):
    """The physical object resting on a storage shelf.

    ``retention_until`` is calculated automatically from the category's
    retention policy the moment the item is received.
    """

    found_report = models.OneToOneField(
        "reports.FoundReport", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stored_item",
    )
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.PROTECT, related_name="stored_items"
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    color = models.ForeignKey(
        "catalog.Color", on_delete=models.PROTECT, related_name="stored_items"
    )
    photo = models.ImageField(upload_to="stored_items/%Y/%m/", null=True, blank=True)
    shelf_code = models.CharField(max_length=16)
    received_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_items"
    )
    retention_until = models.DateField()
    status = models.CharField(
        max_length=16, choices=STORED_STATUSES, default="in_storage", db_index=True
    )

    objects = StoredItemQuerySet.as_manager()

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["category", "status"], name="storeditem_cat_status_idx"),
            models.Index(fields=["status", "retention_until"], name="storeditem_status_ret_idx"),
        ]

    def __str__(self):
        return f"{self.shelf_code} — {self.title} ({self.status})"

    def calculate_retention_until(self, received):
        """Retention deadline = received date + category retention days."""
        received_day = timezone.localdate(received)
        return received_day + timedelta(days=self.category.retention_days)

    def save(self, *args, **kwargs):
        if self._state.adding:
            base = timezone.now()
        else:
            old = (
                StoredItem.objects.filter(pk=self.pk)
                .values_list("category_id", "retention_until")
                .first()
            )
            category_changed = old is None or old[0] != self.category_id
            base = self.received_at if (category_changed or self.retention_until is None) else None
        if base is not None:
            self.retention_until = self.calculate_retention_until(base)
        super().save(*args, **kwargs)


class ItemStatusLog(models.Model):
    """Audit trail of status transitions for a stored item."""

    item = models.ForeignKey(
        StoredItem, on_delete=models.CASCADE, related_name="status_logs"
    )
    old_status = models.CharField(max_length=16)
    new_status = models.CharField(max_length=16)
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="item_status_logs"
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ItemStatusLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["item", "-created_at"], name="statuslog_item_time_idx"),
        ]

    def __str__(self):
        return f"{self.item.shelf_code}: {self.old_status} → {self.new_status} by {self.staff_id}"
