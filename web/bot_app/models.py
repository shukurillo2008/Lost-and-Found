from django.db import models

LANGUAGE_CHOICES = (
    ("uz", "Uzbek"),
    ("ru", "Russian"),
    ("en", "English"),
)


class TelegramUser(models.Model):
    """Telegram user profile. Office staff never use this identity."""

    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    username = models.CharField(max_length=64, blank=True, null=True)
    display_name = models.CharField(max_length=128)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default="uz")
    student_staff_id = models.CharField(max_length=64, blank=True, null=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.display_name} ({self.telegram_id})"
