"""Tests for the ``seed_demo`` management command (course §4.6 demo data).

Locked behaviors: the command is idempotent even when called twice in one
process, the handover history is internally consistent (confirmed match →
handover → returned item/found/lost reports → audit log), historical dates
are ordered, and every returned item has an act while no in-storage item
does.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

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
