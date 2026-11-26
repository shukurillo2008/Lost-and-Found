"""Tests for the office found-reports table (reports_found_list)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bot_app.models import TelegramUser
from catalog.models import Category, Color, Location
from catalog.translation import disabled
from reports.models import FoundReport
from storage.models import StoredItem


class FoundReportListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        with disabled():
            cls.staff = User.objects.create_user("found_staff", password="pw", is_staff=True)
            cls.plain = User.objects.create_user("found_plain", password="pw", is_staff=False)
            cls.finder = TelegramUser.objects.create(
                telegram_id=920001, display_name="Found Finder", language="uz"
            )
            cls.category = Category.objects.create(
                name_uz="FoundTest Bags", emoji="x", retention_days=30
            )
            cls.color = Color.objects.create(name_uz="FoundTest Black")
            cls.location = Location.objects.create(
                building_uz="FoundTest Main", area_uz="FoundTest Hall"
            )
            cls.handed = FoundReport.objects.create(
                reporter=cls.finder, category=cls.category, color=cls.color,
                location=cls.location, title="handed black bag",
                description="handed bag desc", date_found=timezone.localdate(),
                custody="handed_to_office", finder_contact_allowed=True,
                status="registered",
            )
            cls.kept = FoundReport.objects.create(
                reporter=cls.finder, category=cls.category, color=cls.color,
                location=cls.location, title="kept blue bag",
                description="kept bag desc",
                date_found=timezone.localdate() - timedelta(days=1),
                custody="kept_by_finder", finder_contact_allowed=False,
                status="open",
            )
            cls.item = StoredItem.objects.create(
                found_report=cls.handed, category=cls.category, color=cls.color,
                title="handed black bag", description="handed bag desc",
                shelf_code="FND-01", received_by=cls.staff,
            )

    def test_requires_staff_login(self):
        response = self.client.get(reverse("reports_found_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

        self.client.force_login(self.plain)
        response = self.client.get(reverse("reports_found_list"))
        self.assertEqual(response.status_code, 403)

    def test_table_lists_all_found_reports_and_linked_item(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports_found_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "handed black bag")
        self.assertContains(response, "kept blue bag")
        self.assertContains(response, "FND-01")
        self.assertContains(
            response, reverse("storage_item_detail", args=[self.item.pk])
        )

    def test_custody_filter(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports_found_list"), {"custody": "kept_by_finder"}
        )
        self.assertContains(response, "kept blue bag")
        self.assertNotContains(response, "handed black bag")

        response = self.client.get(
            reverse("reports_found_list"), {"custody": "handed_to_office"}
        )
        self.assertContains(response, "handed black bag")
        self.assertNotContains(response, "kept blue bag")

    def test_status_filter(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports_found_list"), {"status": "open"})
        self.assertContains(response, "kept blue bag")
        self.assertNotContains(response, "handed black bag")

        response = self.client.get(
            reverse("reports_found_list"), {"status": "registered"}
        )
        self.assertContains(response, "handed black bag")
        self.assertNotContains(response, "kept blue bag")

    def test_search_matches_title_and_description(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports_found_list"), {"q": "kept"})
        self.assertContains(response, "kept blue bag")
        self.assertNotContains(response, "handed black bag")

        response = self.client.get(reverse("reports_found_list"), {"q": "handed bag desc"})
        self.assertContains(response, "handed black bag")
        self.assertNotContains(response, "kept blue bag")

    def test_date_range_filter(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports_found_list"),
            {"date_from": timezone.localdate().isoformat()},
        )
        self.assertContains(response, "handed black bag")
        self.assertNotContains(response, "kept blue bag")
