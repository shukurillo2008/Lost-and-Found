"""Seed ONLY the reference tables: campus locations, categories and colours.

The full demo seeder (``seed_demo``) also creates staff/Telegram users and
report history. When the database must stay otherwise empty — e.g. a clean
defence run where every report is entered live — this command fills the
minimum reference data the bot and the office forms need.

It reuses the exact tables from ``seed_demo`` (same buildings, areas, category
retention policies and colours), is idempotent, and never touches reports,
storage items or user accounts.

Usage::

    python web/manage.py seed_reference
"""
from django.core.management.base import BaseCommand

from catalog.models import Category, Color, Location
from catalog.management.commands.seed_demo import BUILDINGS, CATEGORIES, COLORS


class Command(BaseCommand):
    help = "Seed campus locations, categories and colours (no users, no reports)."

    def handle(self, *args, **options):
        locations = self._seed_locations()
        categories = self._seed_categories()
        colors = self._seed_colors()
        self.stdout.write(self.style.SUCCESS(
            "seed_reference finished. Created in this run: locations=%d"
            " categories=%d colors=%d. Totals: locations=%d categories=%d"
            " colors=%d"
            % (
                locations, categories, colors,
                Location.objects.count(), Category.objects.count(), Color.objects.count(),
            )
        ))

    def _seed_locations(self):
        """Buildings + areas, trilingual; keyed by the canonical uz values."""
        created = 0
        for building_uz, (building_ru, building_en, areas) in BUILDINGS.items():
            for area_uz, area_ru, area_en in areas:
                location, was_created = Location.objects.get_or_create(
                    building_uz=building_uz, area_uz=area_uz,
                    defaults={
                        "building_en": building_en, "building_ru": building_ru,
                        "area_en": area_en, "area_ru": area_ru,
                    },
                )
                if not was_created:
                    Location.objects.filter(pk=location.pk).update(
                        building_en=building_en, building_ru=building_ru,
                        area_en=area_en, area_ru=area_ru,
                    )
                created += was_created
        return created

    def _seed_categories(self):
        """Categories with their retention policy and bot emoji."""
        created = 0
        for name_uz, name_ru, name_en, emoji, retention in CATEGORIES:
            _, was_created = Category.objects.get_or_create(
                name_uz=name_uz,
                defaults={"name_ru": name_ru, "name_en": name_en,
                          "emoji": emoji, "retention_days": retention},
            )
            Category.objects.filter(name_uz=name_uz).update(
                name_ru=name_ru, name_en=name_en, emoji=emoji, retention_days=retention,
            )
            created += was_created
        return created

    def _seed_colors(self):
        """Fixed colour list used for consistent tagging and matching."""
        created = 0
        for name_uz, name_ru, name_en in COLORS:
            _, was_created = Color.objects.get_or_create(
                name_uz=name_uz,
                defaults={"name_ru": name_ru, "name_en": name_en},
            )
            Color.objects.filter(name_uz=name_uz).update(name_ru=name_ru, name_en=name_en)
            created += was_created
        return created
