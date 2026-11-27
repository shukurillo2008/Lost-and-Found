"""Unit tests for the daily office digest (course §4.4).

Locked behaviors: the digest text carries the retention lists and the
queue counters, HTML in item titles is escaped, sending is gated by the
local digest hour, one local date can be sent only once (restart-safe),
a failed send releases the slot for the next tick, and the date follows
``settings.TIME_ZONE`` rather than the container's UTC clock.
"""
import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Color, Location
from catalog.translation import disabled
from matching.models import MatchSuggestion
from reports.models import FoundReport, LostReport
from storage.models import StoredItem

from .digest import MAX_ATTEMPTS, build_digest, digest_hour, send_daily_digest
from .models import DigestRun, TelegramUser
from .notifications import (
    match_confirmed_text,
    match_confirmed_text_for,
    notify_match_confirmed,
)

OFFICE_SETTINGS = {"BOT_TOKEN": "123:test", "OFFICE_GROUP_ID": "-1001234567890"}


def local_at(hour: int, minute: int = 0, days: int = 0) -> datetime:
    """Aware datetime in the project timezone (Asia/Tashkent)."""
    base = timezone.localtime() + timedelta(days=days)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


class DigestTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        with disabled():
            cls.staff = User.objects.create_user("digest_staff", password="pw", is_staff=True)
            cls.reporter = cls._telegram_user()
            cls.category = Category.objects.create(
                name_uz="DigestTest Electronics", emoji="x", retention_days=30
            )
            cls.color = Color.objects.create(name_uz="DigestTest Black")
            cls.location = Location.objects.create(
                building_uz="DigestTest Main", area_uz="DigestTest Hall"
            )
            cls.expiring = StoredItem.objects.create(
                category=cls.category, color=cls.color, title="expiring umbrella",
                description="blue umbrella", shelf_code="DGT-01", received_by=cls.staff,
            )
            cls.ready = StoredItem.objects.create(
                category=cls.category, color=cls.color, title="ready charger",
                description="usb charger", shelf_code="DGT-02", received_by=cls.staff,
            )
            cls.far = StoredItem.objects.create(
                category=cls.category, color=cls.color, title="far notebook",
                description="lined notebook", shelf_code="DGT-03", received_by=cls.staff,
            )
        today = timezone.localdate()
        StoredItem.objects.filter(pk=cls.expiring.pk).update(
            retention_until=today + timedelta(days=3)
        )
        StoredItem.objects.filter(pk=cls.ready.pk).update(
            retention_until=today - timedelta(days=2)
        )
        StoredItem.objects.filter(pk=cls.far.pk).update(
            retention_until=today + timedelta(days=20)
        )
        with disabled():
            cls.open_report = LostReport.objects.create(
                reporter=cls.reporter, category=cls.category, color=cls.color,
                location=cls.location, title="lost umbrella", description="blue",
                date_lost=today,
            )
            LostReport.objects.create(
                reporter=cls.reporter, category=cls.category, color=cls.color,
                location=cls.location, title="old report", description="old",
                date_lost=today - timedelta(days=120), status="expired",
            )
        cls.suggestion = MatchSuggestion.objects.create(
            lost_report=cls.open_report, stored_item=cls.expiring,
            score=9, created_by="system",
        )

    @staticmethod
    def _telegram_user():
        from .models import TelegramUser

        return TelegramUser.objects.create(
            telegram_id=900010, display_name="Digest Reporter", language="uz"
        )


class DigestTextTests(DigestTestBase):
    def test_counts_match_the_database(self):
        _text, counts = build_digest()
        self.assertEqual(counts["in_storage"], 3)
        self.assertEqual(counts["expiring"], 1)
        self.assertEqual(counts["ready_for_disposal"], 1)
        self.assertEqual(counts["open_reports"], 1)
        self.assertEqual(counts["pending_matches"], 1)
        self.assertEqual(
            counts["received_today"],
            StoredItem.objects.filter(received_at__date=timezone.localdate()).count(),
        )

    def test_text_lists_expiring_and_ready_items(self):
        text, _counts = build_digest()
        self.assertIn("Kunlik hisobot", text)
        self.assertIn("DGT-01", text)
        self.assertIn("expiring umbrella", text)
        self.assertIn("DGT-02", text)
        self.assertIn("ready charger", text)
        self.assertNotIn("DGT-03", text)   # 20 days left: not in either list
        self.assertLessEqual(len(text), 4096)

    def test_item_titles_are_html_escaped(self):
        StoredItem.objects.filter(pk=self.expiring.pk).update(
            title="umbrella <b>bold</b>"
        )
        text, _counts = build_digest()
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", text)
        self.assertNotIn("umbrella <b>bold</b>", text)

    @patch("bot_app.digest.MAX_LISTED", 200)
    def test_long_digest_is_capped_at_the_telegram_limit(self):
        today = timezone.localdate()
        long_title = ("very long umbrella title " * 6)[:120]
        for index in range(120):
            item = StoredItem.objects.create(
                category=self.category, color=self.color, title=long_title,
                description="x", shelf_code=f"CAP-{index:03d}",
                received_by=self.staff,
            )
            StoredItem.objects.filter(pk=item.pk).update(
                retention_until=today + timedelta(days=2)
            )

        text, counts = build_digest()

        self.assertGreater(counts["expiring"], 120)
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertIn("… yana", text)
        self.assertRegex(text, r"… yana \d+ ta")
        # Every kept item line is a whole HTML fragment.
        self.assertIn("<code>CAP-", text)

    @patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "9"})
    def test_digest_hour_env_is_clamped(self):
        self.assertEqual(digest_hour(), 9)
        with patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "99"}):
            self.assertEqual(digest_hour(), 23)
        with patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "nope"}):
            self.assertEqual(digest_hour(), 9)


@override_settings(**OFFICE_SETTINGS)
class DigestSendTests(DigestTestBase):
    @patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "9"})
    def test_before_the_hour_nothing_is_sent(self):
        now = local_at(8, 59)
        with patch("bot_app.digest.telegram_api.send_message") as send:
            result = send_daily_digest(now=now)
        self.assertEqual(result["status"], "before_hour")
        send.assert_not_called()
        self.assertFalse(DigestRun.objects.filter(sent_on=now.date()).exists())

    @patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "9"})
    def test_sends_once_per_local_date(self):
        now = local_at(9, 0)
        with patch(
            "bot_app.digest.telegram_api.send_message",
            return_value={"message_id": 77},
        ) as send:
            first = send_daily_digest(now=now)
            second = send_daily_digest(now=now)
            forced = send_daily_digest(now=now, force=True)
        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "already_sent")
        self.assertEqual(forced["status"], "already_sent")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], -1001234567890)
        run = DigestRun.objects.get(sent_on=now.date())
        self.assertEqual(run.message_id, 77)
        self.assertEqual(run.counts["in_storage"], 3)

    @patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "9", "DIGEST_RETRY_MINUTES": "10"})
    def test_failed_send_retries_after_the_cooldown(self):
        now = local_at(9, 0, days=1)
        with patch("bot_app.digest.telegram_api.send_message", return_value=None) as send:
            failed = send_daily_digest(now=now)
            cooling = send_daily_digest(now=now)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(cooling["status"], "retry_later")
        self.assertEqual(send.call_count, 1)
        run = DigestRun.objects.get(sent_on=now.date())
        self.assertIsNone(run.message_id)
        self.assertEqual(run.attempts, 1)

        with patch.dict(os.environ, {"DIGEST_RETRY_MINUTES": "0"}), patch(
            "bot_app.digest.telegram_api.send_message",
            return_value={"message_id": 78},
        ):
            retried = send_daily_digest(now=now)
        self.assertEqual(retried["status"], "sent")
        run.refresh_from_db()
        self.assertEqual(run.message_id, 78)
        self.assertEqual(run.attempts, 2)

    @patch.dict(os.environ, {"WORKER_DIGEST_HOUR": "9", "DIGEST_RETRY_MINUTES": "0"})
    def test_gives_up_after_max_attempts(self):
        now = local_at(9, 0, days=3)
        DigestRun.objects.create(
            sent_on=now.date(), attempts=MAX_ATTEMPTS, last_attempt_at=now
        )
        with patch("bot_app.digest.telegram_api.send_message") as send:
            result = send_daily_digest(now=now)
        self.assertEqual(result["status"], "gave_up")
        send.assert_not_called()

    def test_missing_token_or_group_is_disabled(self):
        now = local_at(9, 0, days=2)
        with override_settings(BOT_TOKEN=""):
            self.assertEqual(send_daily_digest(now=now)["status"], "disabled")
        with override_settings(OFFICE_GROUP_ID=""):
            self.assertEqual(send_daily_digest(now=now)["status"], "disabled")
        with override_settings(OFFICE_GROUP_ID="not-a-number"):
            self.assertEqual(send_daily_digest(now=now)["status"], "disabled")
        self.assertFalse(DigestRun.objects.filter(sent_on=now.date()).exists())

    def test_sent_on_follows_the_project_timezone(self):
        utc = datetime(2026, 11, 13, 4, 0, tzinfo=dt_timezone.utc)  # 09:00 Tashkent
        expected = timezone.localtime(utc).date()
        with patch(
            "bot_app.digest.telegram_api.send_message",
            return_value={"message_id": 79},
        ):
            result = send_daily_digest(now=utc, force=True)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["sent_on"], expected.isoformat())
        self.assertTrue(DigestRun.objects.filter(sent_on=expected).exists())

NOTIFY_SETTINGS = {"BOT_TOKEN": "123:test"}


@override_settings(**NOTIFY_SETTINGS)
class MatchConfirmedNotificationTests(TestCase):
    """A confirmed match must reach the lost reporter with the finder's
    contact details (username always, phone when shared), but only when the
    finder opted in to contact sharing."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user("notify_staff", password="pw", is_staff=True)
        with disabled():
            cls.finder = TelegramUser.objects.create(
                telegram_id=910001, username="finder_user", phone="+998901112233",
                display_name="Ali Finder", language="uz",
            )
            cls.owner = TelegramUser.objects.create(
                telegram_id=910002, display_name="Vali Owner", language="uz",
            )
            cls.category = Category.objects.create(
                name_uz="NotifyTest Phones", emoji="x", retention_days=30
            )
            cls.color = Color.objects.create(name_uz="NotifyTest Black")
            cls.location = Location.objects.create(
                building_uz="NotifyTest Main", area_uz="NotifyTest Hall"
            )
            cls.found = FoundReport.objects.create(
                reporter=cls.finder, category=cls.category, color=cls.color,
                location=cls.location, title="black phone", description="black phone",
                date_found=timezone.localdate(), custody="handed_to_office",
                finder_contact_allowed=True, status="registered",
            )
            cls.lost = LostReport.objects.create(
                reporter=cls.owner, category=cls.category, color=cls.color,
                location=cls.location, title="black phone", description="black phone",
                date_lost=timezone.localdate(), status="open",
            )
            cls.item = StoredItem.objects.create(
                found_report=cls.found, category=cls.category, color=cls.color,
                title="black phone", description="black phone",
                shelf_code="NTF-01", received_by=cls.staff,
            )
            cls.suggestion = MatchSuggestion.objects.create(
                lost_report=cls.lost, stored_item=cls.item, created_by="system",
                score=12, score_breakdown={"color": 3},
            )

    def test_confirmed_text_includes_username_and_phone(self):
        text = match_confirmed_text(self.suggestion)
        self.assertIn("@finder_user", text)
        self.assertIn("+998901112233", text)
        self.assertIn("Ali Finder", text)
        self.assertIn("black phone", text)

    def test_contact_is_hidden_without_consent(self):
        FoundReport.objects.filter(pk=self.found.pk).update(finder_contact_allowed=False)
        suggestion = MatchSuggestion.objects.select_related(
            "lost_report__reporter", "stored_item__found_report__reporter"
        ).get(pk=self.suggestion.pk)
        text = match_confirmed_text(suggestion)
        self.assertNotIn("@finder_user", text)
        self.assertNotIn("+998901112233", text)
        self.assertIn("ofis xodimlari", text)

    def test_notification_goes_to_the_lost_reporter(self):
        with patch(
            "bot_app.notifications.telegram_api.send_message",
            return_value={"message_id": 5},
        ) as send:
            sent = notify_match_confirmed(self.suggestion)
        self.assertTrue(sent)
        send.assert_called_once()
        chat_id, body = send.call_args.args
        self.assertEqual(chat_id, self.owner.telegram_id)
        self.assertIn("@finder_user", body)
        self.assertIn("+998901112233", body)

    def test_missing_token_is_a_noop(self):
        with override_settings(BOT_TOKEN=""), patch(
            "bot_app.notifications.telegram_api.send_message"
        ) as send:
            self.assertFalse(notify_match_confirmed(self.suggestion))
        send.assert_not_called()

    def test_found_report_only_suggestion_uses_finder_contact(self):
        with disabled():
            suggestion = MatchSuggestion.objects.create(
                lost_report=self.lost, found_report=self.found,
                created_by="user", score=12,
            )
        text = match_confirmed_text(suggestion)
        self.assertIn("@finder_user", text)
        self.assertIn("+998901112233", text)

    def test_match_confirmed_text_for_fetches_by_id(self):
        text = match_confirmed_text_for(self.suggestion.pk, "en")
        self.assertIn("@finder_user", text)
        self.assertIn("Match confirmed", text)
        self.assertIsNone(match_confirmed_text_for(999999, "en"))

    def test_office_confirm_triggers_the_notification(self):
        self.client.force_login(self.staff)
        with patch(
            "bot_app.notifications.telegram_api.send_message",
            return_value={"message_id": 6},
        ) as send:
            response = self.client.post(
                reverse("reports_match_review"),
                {"action": "confirm", "suggestion_id": self.suggestion.pk},
            )
        self.assertEqual(response.status_code, 302)
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status, "confirmed")
        send.assert_called_once()
        chat_id, body = send.call_args.args
        self.assertEqual(chat_id, self.owner.telegram_id)
        self.assertIn("@finder_user", body)
