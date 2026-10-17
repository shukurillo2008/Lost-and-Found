from django.contrib import admin

from .models import TelegramUser


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("telegram_id", "display_name", "username", "language", "is_blocked", "created_at")
    list_filter = ("language", "is_blocked")
    search_fields = ("telegram_id", "display_name", "username")
    readonly_fields = ("telegram_id", "created_at")
