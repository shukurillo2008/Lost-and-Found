from django.contrib import admin

from .models import ItemStatusLog, StoredItem


@admin.register(StoredItem)
class StoredItemAdmin(admin.ModelAdmin):
    list_display = (
        "id", "shelf_code", "title", "category", "color", "received_at",
        "retention_until", "status",
    )
    list_filter = ("status", "category", "shelf_code")
    list_select_related = ("category", "color", "found_report")
    search_fields = ("title", "description", "shelf_code")
    readonly_fields = ("retention_until", "received_at")
    raw_id_fields = ("found_report", "received_by")


@admin.register(ItemStatusLog)
class ItemStatusLogAdmin(admin.ModelAdmin):
    list_display = ("id", "item", "old_status", "new_status", "staff", "created_at")
    list_filter = ("new_status",)
    search_fields = ("item__title", "item__shelf_code")
    readonly_fields = ("created_at",)
