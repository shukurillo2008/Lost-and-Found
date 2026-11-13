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


class DigestRun(models.Model):
    """One row per local date on which the office digest was sent.

    The unique ``sent_on`` is the idempotency guard for the worker: a
    restart, a duplicate tick or a second process cannot send the same
    day's digest twice. A failed send deletes the row so the next tick
    retries instead of silently losing the day.
    """

    sent_on = models.DateField(unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)   # first attempt
    counts = models.JSONField(default=dict, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-sent_on"]

    def __str__(self):
        return f"digest {self.sent_on}"
