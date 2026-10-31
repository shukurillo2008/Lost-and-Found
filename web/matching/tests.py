"""Unit tests for the matching engine and the duplicate-suggestion guard.

Locked behaviors (course §5 Tests + README milestone 6): identical category
required (score 0 otherwise), color exactly +3, temporal window (found no
earlier than the loss, at most 14 days later) worth +2, same building +2
with +1 more for the same area, word overlap over title+description
lower-cased with stop words removed and capped at +4, the strictly-over-5
worker threshold, and the DB-level rule that a lost+stored pair can never
hold more than one suggestion (``unique_lost_item_suggestion``) — the
guarantee the worker leans on for restart-safety.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from bot_app.models import TelegramUser
from catalog.models import Category, Color, Location
from catalog.translation import disabled
from matching.engine import (
    MIN_SYSTEM_SCORE,
    match_score,
    score_breakdown,
    score_from_breakdown,
    strong_enough,
    tokenize,
)
from matching.models import MatchSuggestion
from reports.models import FoundReport, LostReport
from storage.models import StoredItem


def day(delta: int):
    return timezone.localdate() + timedelta(days=delta)


class MatchingTestBase(TestCase):
    """Shared reference data, all under EngineTest-prefixed natural keys."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        with disabled():
            cls.staff = User.objects.create_user("engine_staff", password="pw", is_staff=True)
            cls.reporter = TelegramUser.objects.create(
                telegram_id=900001, display_name="Engine Reporter", language="en"
            )
            cls.cat_electronics = Category.objects.create(
                name_uz="EngineTest Electronics", emoji="?", retention_days=90
            )
            cls.cat_clothing = Category.objects.create(
                name_uz="EngineTest Clothing", emoji="?", retention_days=30
            )
            cls.color_black = Color.objects.create(name_uz="EngineTest Black")
            cls.color_red = Color.objects.create(name_uz="EngineTest Red")
            cls.loc_main_study = Location.objects.create(
                building_uz="EngineTest Main", area_uz="EngineTest Study"
            )
            cls.loc_main_cafe = Location.objects.create(
                building_uz="EngineTest Main", area_uz="EngineTest Canteen"
            )
            cls.loc_sport = Location.objects.create(
                building_uz="EngineTest Sport", area_uz="EngineTest Pitch"
            )

    def make_lost(
        self, *, category=None, color=None, location=None, days_ago=3,
        title="black wallet", description="brown leather wallet",
    ):
        with disabled():
            return LostReport.objects.create(
                reporter=self.reporter, category=category or self.cat_electronics,
                title=title, description=description,
                color=color or self.color_black, location=location,
                date_lost=day(-days_ago), status="open",
            )

    def make_found(
        self, *, category=None, color=None, location=None, days_ago=1,
        title="gold bracelet", description="thin golden chain",
    ):
        with disabled():
            return FoundReport.objects.create(
                reporter=self.reporter, category=category or self.cat_electronics,
                title=title, description=description,
                color=color or self.color_red, location=location,
                date_found=day(-days_ago), custody="handed_to_office", status="open",
            )

    def make_stored(
        self, *, found=None, category=None, color=None,
        title="gold bracelet", description="thin golden chain",
    ):
        with disabled():
            return StoredItem.objects.create(
                found_report=found, category=category or self.cat_electronics,
                title=title, description=description,
                color=color or self.color_red, shelf_code="TST-01", received_by=self.staff,
            )


class EngineScoringTests(MatchingTestBase):
    def test_category_mismatch_scores_exactly_zero(self):
        lost = self.make_lost(category=self.cat_clothing, color=self.color_red)
        item = self.make_stored()
        breakdown = score_breakdown(lost, item)
        self.assertEqual(match_score(lost, item), 0)
        self.assertEqual(set(breakdown), {"category_match"})
        self.assertIs(breakdown["category_match"], False)

    def test_color_is_exactly_three_points(self):
        lost = self.make_lost(location=self.loc_main_study)
        found = self.make_found(color=self.color_black, location=self.loc_sport, days_ago=10)
        breakdown = score_breakdown(lost, found)
        self.assertEqual(breakdown["color"], 3)
        self.assertEqual(match_score(lost, found), 3)  # nothing else fires

    def test_temporal_only_when_found_at_or_after_loss_within_days(self):
        lost = self.make_lost(days_ago=20, color=self.color_black)
        for found_ago, expected in ((20, True), (6, True), (5, False), (21, False)):
            with self.subTest(found_ago=found_ago):
                found = self.make_found(
                    days_ago=found_ago, color=self.color_red, location=self.loc_sport
                )
                breakdown = score_breakdown(lost, found)
                self.assertIs("temporal" in breakdown, expected)
                self.assertNotIn("color", breakdown)
                self.assertEqual(match_score(lost, found), 2 if expected else 0)

    def test_location_bonus_stack(self):
        lost = self.make_lost(color=self.color_black, location=self.loc_main_study)
        same_row = self.make_found(location=self.loc_main_study, color=self.color_red, days_ago=10)
        breakdown = score_breakdown(lost, same_row)
        self.assertEqual(breakdown["building"], 2)
        self.assertEqual(breakdown["area"], 1)
        self.assertEqual(match_score(lost, same_row), 3)

        other_area = self.make_found(location=self.loc_main_cafe, color=self.color_red, days_ago=10)
        breakdown = score_breakdown(lost, other_area)
        self.assertEqual(breakdown["building"], 2)
        self.assertNotIn("area", breakdown)
        self.assertEqual(match_score(lost, other_area), 2)

        other_building = self.make_found(location=self.loc_sport, color=self.color_red, days_ago=10)
        breakdown = score_breakdown(lost, other_building)
        self.assertNotIn("building", breakdown)
        self.assertNotIn("area", breakdown)
        self.assertEqual(match_score(lost, other_building), 0)

    def test_word_overlap_capped_at_four(self):
        lost = self.make_lost(
            title="red umbrella long handle", description="wooden automatic fold",
            color=self.color_black, days_ago=5,
        )
        found = self.make_found(
            title="red umbrella long handle wooden", description="automatic fold spare",
            color=self.color_red, location=self.loc_sport, days_ago=2,
        )
        breakdown = score_breakdown(lost, found)
        # Seven shared tokens on one side -> still just +4.
        self.assertEqual(breakdown["words"], 4)
        self.assertEqual(match_score(lost, found), 6)  # words 4 + temporal 2

    def test_tokenizer_lowercases_dedups_and_skips_stop_words(self):
        # yo'q and yoq both normalize to "yoq" — which is a stop word,
        # so both spellings are dropped; "va"/"the" likewise.
        self.assertEqual(tokenize("Yo'q yoq VA The charger!"), {"charger"})
        self.assertEqual(tokenize("Black BLACK black"), {"black"})
        self.assertEqual(tokenize(None), set())

    def test_worker_threshold_is_strictly_above_five(self):
        self.assertEqual(MIN_SYSTEM_SCORE, 5)
        self.assertFalse(strong_enough(5))
        self.assertTrue(strong_enough(6))

    def test_found_report_and_linked_item_score_identically(self):
        lost = self.make_lost(
            title="black power bank", description="20000 mah charger",
            color=self.color_black, location=self.loc_main_study, days_ago=5,
        )
        found = self.make_found(
            title="black power bank", description="charger included",
            color=self.color_black, location=self.loc_main_study, days_ago=3,
        )
        with disabled():
            item = StoredItem.objects.create(
                found_report=found, category=self.cat_electronics,
                title="black power bank", description="charger included",
                color=self.color_black, shelf_code="TST-02", received_by=self.staff,
            )
        score_item = match_score(lost, item)
        self.assertEqual(score_item, match_score(lost, found))
        self.assertGreater(score_item, MIN_SYSTEM_SCORE)

    def test_only_score_keys_are_summed(self):
        # Diagnostics must never leak into the score, whatever their values.
        self.assertEqual(
            score_from_breakdown(
                {"color": 3, "temporal": 2, "building": 2, "area": 1, "words": 4,
                 "shared_words": ["lots", "of", "junk"], "lost_date": "2026-01-01"}
            ),
            12,
        )


class DuplicateSuggestionGuardsTests(MatchingTestBase):
    def test_same_lost_stored_pair_cannot_be_suggested_twice(self):
        lost = self.make_lost()
        stored = self.make_stored()
        with disabled():
            MatchSuggestion.objects.create(
                lost_report=lost, stored_item=stored, created_by="system",
                score=12, score_breakdown={"color": 3},
            )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MatchSuggestion.objects.create(
                    lost_report=lost, stored_item=stored, created_by="user",
                    score=0, score_breakdown={},
                )
        self.assertEqual(MatchSuggestion.objects.filter(lost_report=lost).count(), 1)

    def test_get_or_create_is_restart_safe_idempotent(self):
        # The worker's restart-safe pattern: get_or_create must reuse the row.
        lost = self.make_lost()
        stored = self.make_stored()
        expectation = {1: True, 2: False}  # first call creates, second reuses
        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                suggestion, created = MatchSuggestion.objects.get_or_create(
                    lost_report=lost, stored_item=stored,
                    defaults={"created_by": "system", "score": 7, "score_breakdown": {}},
                )
                self.assertIs(created, expectation[attempt])
        self.assertEqual(
            MatchSuggestion.objects.filter(lost_report=lost, stored_item=stored).count(),
            1,
        )
