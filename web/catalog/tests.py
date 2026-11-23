"""Tests for the seeding management commands (course §4.6 demo data).

Locked behaviors: ``seed_demo`` is idempotent even when called twice in one
process, the handover history is internally consistent (confirmed match →
handover → returned item/found/lost reports → audit log), historical dates
are ordered, and every returned item has an act while no in-storage item
does. ``seed_reference`` fills only the reference tables.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from catalog.models import Category, Color, Location
from matching.models import Handover, MatchSuggestion
from reports.models import FoundReport, LostReport
from storage.models import ItemStatusLog, StoredItem


class SeedDemoTests(TestCase):
    @staticmethod
    def run_seed():
        call_command("seed_demo", stdout=StringIO())

    def test_seed_creates_consistent_handover_history(self):
        self.run_seed()

        handovers = Handover.objects.select_related(
            "stored_item", "stored_item__found_report", "lost_report", "lost_report__reporter", "staff"
        )
        self.assertEqual(handovers.count(), 8)   # 6 fixed acts + 2 repaired returned items
        self.assertEqual(MatchSuggestion.objects.count(), 8)
        self.assertGreaterEqual(ItemStatusLog.objects.count(), 11)

        for handover in handovers:
            item = handover.stored_item
            lost = handover.lost_report
            self.assertEqual(item.status, "returned")
            self.assertEqual(lost.status, "returned")
            self.assertEqual(handover.receiver_name, lost.reporter.display_name)
            self.assertIsNotNone(handover.staff)
            self.assertLessEqual(handover.handed_at, timezone.now())
            self.assertGreaterEqual(handover.handed_at, item.received_at)

            suggestion = MatchSuggestion.objects.get(stored_item=item, status="confirmed")
            self.assertEqual(suggestion.lost_report_id, lost.pk)
            self.assertGreater(suggestion.score, 5)
            self.assertIsNotNone(suggestion.reviewed_by)
            self.assertIsNotNone(suggestion.reviewed_at)

            self.assertTrue(
                ItemStatusLog.objects.filter(
                    item=item, old_status="in_storage", new_status="returned"
                ).exists()
            )
            if item.found_report_id:
                self.assertEqual(item.found_report.status, "returned")

        self.assertFalse(
            StoredItem.objects.filter(status="returned", handover__isnull=True).exists()
        )
        self.assertFalse(
            StoredItem.objects.filter(status="in_storage", handover__isnull=False).exists()
        )
        for item in StoredItem.objects.filter(status__in=("disposed", "transferred")):
            self.assertTrue(
                ItemStatusLog.objects.filter(item=item, new_status=item.status).exists()
            )

        dates = {handover.handed_at.date() for handover in handovers}
        self.assertGreaterEqual(len(dates), 5)

    def test_seed_fills_every_language_stream(self):
        """Mock data is trilingual with Uzbek as the primary language."""
        self.run_seed()

        for model in (LostReport, FoundReport):
            reports = list(model.objects.all())
            self.assertTrue(reports)
            for report in reports:
                with self.subTest(model=model.__name__, pk=report.pk):
                    self.assertEqual(report.title, report.title_uz)
                    for lang in ("uz", "ru", "en"):
                        self.assertTrue(getattr(report, f"title_{lang}"), f"title_{lang}")
                        self.assertTrue(
                            getattr(report, f"description_{lang}"), f"description_{lang}"
                        )
                    self.assertNotEqual(report.title_uz, report.title_ru)
                    self.assertNotEqual(report.title_uz, report.title_en)

    def test_seed_is_idempotent_in_one_process(self):
        self.run_seed()
        counts = (
            LostReport.objects.count(),
            FoundReport.objects.count(),
            StoredItem.objects.count(),
            Handover.objects.count(),
            MatchSuggestion.objects.count(),
            ItemStatusLog.objects.count(),
        )
        self.run_seed()
        self.assertEqual(
            (
                LostReport.objects.count(),
                FoundReport.objects.count(),
                StoredItem.objects.count(),
                Handover.objects.count(),
                MatchSuggestion.objects.count(),
                ItemStatusLog.objects.count(),
            ),
            counts,
        )


class SeedReferenceTests(TestCase):
    """``seed_reference`` fills the reference tables and nothing else."""

    @staticmethod
    def run_reference():
        call_command("seed_reference", stdout=StringIO())

    def test_seed_reference_creates_only_reference_rows(self):
        self.run_reference()
        self.assertEqual(Location.objects.count(), 20)
        self.assertEqual(Category.objects.count(), 9)
        self.assertEqual(Color.objects.count(), 12)
        # No transactional data, no accounts.
        self.assertEqual(LostReport.objects.count(), 0)
        self.assertEqual(FoundReport.objects.count(), 0)
        self.assertEqual(StoredItem.objects.count(), 0)
        self.assertEqual(MatchSuggestion.objects.count(), 0)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_seed_reference_is_idempotent(self):
        self.run_reference()
        first = (Location.objects.count(), Category.objects.count(), Color.objects.count())
        self.run_reference()
        self.assertEqual(
            (Location.objects.count(), Category.objects.count(), Color.objects.count()),
            first,
        )

    def test_reference_data_keeps_the_demo_defaults(self):
        self.run_reference()
        category = Category.objects.get(name_uz="Elektronika")
        self.assertEqual(category.retention_days, 90)
        self.assertEqual(category.name_en, "Electronics")
        location = Location.objects.get(building_uz="Kutubxona", area_uz="Kompyuter sinfxonasi")
        self.assertEqual(location.building_en, "Library")
        self.assertEqual(location.area_en, "Computer Lab")
        self.assertEqual(Color.objects.get(name_uz="Qora").name_en, "Black")

    def test_seed_reference_then_seed_demo_does_not_duplicate(self):
        self.run_reference()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Location.objects.count(), 20)
        self.assertEqual(Category.objects.count(), 9)
        self.assertEqual(Color.objects.count(), 12)
