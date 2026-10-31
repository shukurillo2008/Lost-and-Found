"""Unit tests for storage rules (course §5 Tests row).

Covered here — retention date computation (creation, category change,
status-change neutrality), the item status transitions behind the detail
page actions (dispose / transfer: in-storage only, note mandatory, audit
row written), and the handover act closing item, linked found report and
the confirmed lost claim atomically.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bot_app.models import TelegramUser
from catalog.models import Category, Color, Location
from catalog.translation import disabled
from matching.models import Handover, MatchSuggestion
from reports.models import FoundReport, LostReport
from storage.models import ItemStatusLog, StoredItem

HANDOVER_PAYLOAD = {"receiver_name": "Aziz Karimov", "id_last4": "7765", "note": "student id checked"}


class StorageTestBase(TestCase):
    """Reference rows + helpers, behind StorageTest-prefixed natural keys
    (separate from the matching suite so both can share one test database)."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        with disabled():
            cls.staff = User.objects.create_user("vault_staff", password="pw", is_staff=True)
            cls.plain_user = User.objects.create_user("plain_person", password="pw", is_staff=False)
            cls.finder = TelegramUser.objects.create(
                telegram_id=900002, display_name="Finder Owner", language="en"
            )
            cls.claimant = TelegramUser.objects.create(
                telegram_id=900003, display_name="Claim Owner", language="en"
            )
            cls.cat_long = Category.objects.create(
                name_uz="StorageTest Electronics", emoji="?", retention_days=90
            )
            cls.cat_short = Category.objects.create(
                name_uz="StorageTest Clothing", emoji="?", retention_days=30
            )
            cls.color = Color.objects.create(name_uz="StorageTest Black")
            cls.location = Location.objects.create(
                building_uz="StorageTest Main", area_uz="StorageTest Study"
            )

    def make_found(self, *, status="registered"):
        with disabled():
            return FoundReport.objects.create(
                reporter=self.finder, category=self.cat_long,
                title="black power bank", description="20000 mah charger",
                color=self.color, location=self.location,
                date_found=timezone.localdate() - timedelta(days=1),
                custody="handed_to_office", status=status,
            )

    def make_stored(self, *, found=None):
        with disabled():
            return StoredItem.objects.create(
                found_report=found, category=self.cat_long,
                title="black power bank", description="20000 mah charger",
                color=self.color, shelf_code="SRT-01", received_by=self.staff,
            )

    def make_lost(self, *, status="open"):
        with disabled():
            return LostReport.objects.create(
                reporter=self.claimant, category=self.cat_long,
                title="black power bank", description="20000 mah charger",
                color=self.color, location=self.location,
                date_lost=timezone.localdate() - timedelta(days=3), status=status,
            )

    def make_claim(self, *, lost, stored):
        with disabled():
            return MatchSuggestion.objects.create(
                lost_report=lost, stored_item=stored, created_by="user",
                score=12, score_breakdown={"color": 3},
                status="confirmed", reviewed_by=self.staff, reviewed_at=timezone.now(),
            )

    @staticmethod
    def handover_url(item):
        return reverse("storage_handover", args=[item.pk])


class RetentionComputationTests(StorageTestBase):
    def test_retention_until_computed_from_category_on_creation(self):
        item = self.make_stored()
        self.assertEqual(item.retention_until, timezone.localdate() + timedelta(days=90))

    def test_category_change_recomputes_retention(self):
        item = self.make_stored()
        received_day = timezone.localdate(item.received_at)
        item.category = self.cat_short
        with disabled():
            item.save()
        item.refresh_from_db()
        self.assertEqual(item.retention_until, received_day + timedelta(days=30))

    def test_status_change_leaves_retention_alone(self):
        item = self.make_stored()
        original = item.retention_until
        item.status = "transferred"
        with disabled():
            item.save()
        item.refresh_from_db()
        self.assertEqual(item.retention_until, original)


class ItemStatusTransitionTests(StorageTestBase):
    def setUp(self):
        self.client.force_login(self.staff)
        self.item = self.make_stored()
        self.url = reverse("storage_item_detail", args=[self.item.pk])

    def test_dispose_without_note_is_rejected(self):
        self.client.post(self.url, {"action": "dispose", "note": "   "}, follow=True)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "in_storage")
        self.assertEqual(self.item.status_logs.count(), 0)

    def test_dispose_writes_status_and_audit_log(self):
        response = self.client.post(
            self.url, {"action": "dispose", "note": "broken beyond repair"}, follow=True
        )
        self.item.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.item.status, "disposed")
        log = self.item.status_logs.get()
        self.assertEqual((log.old_status, log.new_status), ("in_storage", "disposed"))
        self.assertEqual(log.staff, self.staff)
        self.assertEqual(log.note, "broken beyond repair")

    def test_transfer_writes_status_and_audit_log(self):
        self.client.post(self.url, {"action": "transfer", "note": "sent to dean office"}, follow=True)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "transferred")
        self.assertTrue(self.item.status_logs.filter(new_status="transferred").exists())

    def test_actions_rejected_after_item_left_storage(self):
        with disabled():
            self.item.status = "disposed"
            self.item.save()
        self.client.post(self.url, {"action": "transfer", "note": "second attempt"}, follow=True)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, "disposed")
        self.assertEqual(self.item.status_logs.count(), 0)


class HandoverFlowTests(StorageTestBase):
    def setUp(self):
        self.client.force_login(self.staff)

    def kit(self, *, lost_status="open", found_status="registered"):
        found = self.make_found(status=found_status)
        stored = self.make_stored(found=found)
        lost = self.make_lost(status=lost_status)
        claim = self.make_claim(lost=lost, stored=stored)
        return {"found": found, "stored": stored, "lost": lost, "claim": claim}

    def test_anonymous_redirected_to_login(self):
        response = Client().get(self.handover_url(self.make_stored()))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_non_staff_gets_403(self):
        client = Client()
        client.force_login(self.plain_user)
        response = client.get(self.handover_url(self.make_stored()))
        self.assertEqual(response.status_code, 403)

    def test_receiver_prefilled_from_confirmed_claim(self):
        kit = self.kit()
        response = self.client.get(self.handover_url(kit["stored"]))
        self.assertEqual(response.context["receiver_name"], "Claim Owner")

    def test_receiver_prefilled_from_linked_report_without_claim(self):
        found = self.make_found()
        stored = self.make_stored(found=found)
        response = self.client.get(self.handover_url(stored))
        self.assertEqual(response.context["receiver_name"], "Finder Owner")

    def test_handover_closes_item_found_report_and_confirmed_claim(self):
        kit = self.kit(lost_status="open", found_status="registered")
        response = self.client.post(self.handover_url(kit["stored"]), HANDOVER_PAYLOAD, follow=True)
        self.assertEqual(response.status_code, 200)
        kit["stored"].refresh_from_db()
        kit["found"].refresh_from_db()
        kit["lost"].refresh_from_db()
        self.assertEqual(kit["stored"].status, "returned")
        handover = Handover.objects.get(stored_item=kit["stored"])
        self.assertEqual(handover.receiver_name, "Aziz Karimov")
        self.assertEqual(handover.receiver_id_last4, "7765")
        self.assertEqual(handover.lost_report, kit["lost"])
        self.assertEqual(handover.staff, self.staff)
        log = ItemStatusLog.objects.get(item=kit["stored"])
        self.assertEqual((log.old_status, log.new_status), ("in_storage", "returned"))
        self.assertEqual(kit["found"].status, "returned")
        self.assertEqual(kit["lost"].status, "returned")
        # Privacy rule: the receiver digits never land in the audit trail.
        self.assertNotIn("7765", f"{log.old_status}{log.new_status}{log.note}")

    def test_handover_closes_matched_lost_report_too(self):
        kit = self.kit(lost_status="matched")
        self.client.post(self.handover_url(kit["stored"]), HANDOVER_PAYLOAD, follow=True)
        kit["lost"].refresh_from_db()
        kit["stored"].refresh_from_db()
        self.assertEqual(kit["lost"].status, "returned")
        self.assertEqual(kit["stored"].status, "returned")

    def test_unregistered_found_report_stays_open(self):
        kit = self.kit(found_status="open")
        self.client.post(self.handover_url(kit["stored"]), HANDOVER_PAYLOAD, follow=True)
        kit["found"].refresh_from_db()
        self.assertEqual(kit["found"].status, "open")

    def test_handover_rejects_missing_name_and_bad_id_digits(self):
        kit = self.kit()
        bad = (("", "7765"), ("Aziz Karimov", "12345"), ("Aziz Karimov", "12a4"), ("Aziz Karimov", "776"))
        for name, digits in bad:
            with self.subTest(name=name, digits=digits):
                self.client.post(
                    self.handover_url(kit["stored"]),
                    {"receiver_name": name, "id_last4": digits, "note": ""},
                    follow=True,
                )
        self.assertEqual(Handover.objects.count(), 0)
        kit["stored"].refresh_from_db()
        self.assertEqual(kit["stored"].status, "in_storage")
        self.assertEqual(kit["stored"].status_logs.count(), 0)

    def test_item_cannot_be_handed_twice(self):
        kit = self.kit()
        url = self.handover_url(kit["stored"])
        self.client.post(url, HANDOVER_PAYLOAD, follow=True)
        second = self.client.post(url, HANDOVER_PAYLOAD)
        self.assertEqual(second.status_code, 302)  # bounced back to the detail page
        self.assertEqual(Handover.objects.count(), 1)
        kit["stored"].refresh_from_db()
        self.assertEqual(kit["stored"].status, "returned")
