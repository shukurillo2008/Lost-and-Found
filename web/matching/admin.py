from django.contrib import admin

from .models import Handover, MatchSuggestion


@admin.register(MatchSuggestion)
class MatchSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "lost_report", "stored_item", "found_report", "score",
        "created_by", "status", "reviewed_by", "reviewed_at", "created_at",
    )
    list_filter = ("status", "created_by")
    list_select_related = ("lost_report", "stored_item", "found_report")
    search_fields = ("lost_report__title", "stored_item__title", "found_report__title")
    readonly_fields = ("created_at",)
    raw_id_fields = ("lost_report", "stored_item", "found_report")


@admin.register(Handover)
class HandoverAdmin(admin.ModelAdmin):
    list_display = ("id", "stored_item", "receiver_name", "receiver_id_last4", "staff", "handed_at")
    search_fields = ("receiver_name", "stored_item__title")
    readonly_fields = ("handed_at",)
    raw_id_fields = ("stored_item", "lost_report")
