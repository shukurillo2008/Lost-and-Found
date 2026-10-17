from django.contrib import admin

from .models import FoundReport, LostReport


@admin.register(LostReport)
class LostReportAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "category", "color", "reporter", "location", "date_lost", "status", "created_at")
    list_filter = ("status", "category", "color")
    list_select_related = ("category", "color", "reporter", "location")
    search_fields = ("title", "description", "brand_marks", "reporter__display_name", "reporter__telegram_id")
    date_hierarchy = "date_lost"
    raw_id_fields = ("reporter",)


@admin.register(FoundReport)
class FoundReportAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "category", "color", "reporter", "location", "date_found", "custody", "finder_contact_allowed", "status", "created_at")
    list_filter = ("status", "custody", "category", "color", "finder_contact_allowed")
    list_select_related = ("category", "color", "reporter", "location")
    search_fields = ("title", "description", "reporter__display_name", "reporter__telegram_id")
    date_hierarchy = "date_found"
    raw_id_fields = ("reporter",)
