from django.contrib import admin

from .models import DigestRun, TelegramUser


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "display_name", "username", "language", "is_blocked", "created_at")
    list_filter = ("language", "is_blocked")
    search_fields = ("telegram_id", "display_name", "username")
    readonly_fields = ("telegram_id", "created_at")


@admin.register(DigestRun)
class DigestRunAdmin(admin.ModelAdmin):
    list_display = ("sent_on", "sent_at", "attempts", "message_id")
    readonly_fields = (
        "sent_on", "sent_at", "counts", "message_id", "attempts", "last_attempt_at",
    )
