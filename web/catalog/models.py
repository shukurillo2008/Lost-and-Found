from django.db import models

from catalog.translation import apply_to_fields


class TranslatableName(models.Model):
    """Something with a single name in three languages (uz is canonical)."""

    name_uz = models.CharField(max_length=50)
    name_en = models.CharField(max_length=50, blank=True)
    name_ru = models.CharField(max_length=50, blank=True)

    class Meta:
        abstract = True

    def _autofill_name(self) -> None:
        apply_to_fields(self, ["name"])

    def localized_name(self, lang: str) -> str:
        value = getattr(self, f"name_{lang}", "") or ""
        return value or self.name_uz


class Location(models.Model):
    """Hierarchical campus place: building + specific area inside it.

    ``building_uz`` / ``area_uz`` are the canonical fields; en/ru are filled
    automatically for staff (or by the seeder) and stay editable.
    """

    building_uz = models.CharField(max_length=100)
    building_en = models.CharField(max_length=100, blank=True)
    building_ru = models.CharField(max_length=100, blank=True)
    area_uz = models.CharField(max_length=150)
    area_en = models.CharField(max_length=150, blank=True)
    area_ru = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["building_uz", "area_uz"]
        constraints = [
            models.UniqueConstraint(fields=["building_uz", "area_uz"], name="unique_building_area_uz"),
        ]

    def save(self, *args, **kwargs):
        apply_to_fields(self, ["building", "area"])
        super().save(*args, **kwargs)

    def _localized_part(self, base: str, lang: str) -> str:
        value = getattr(self, f"{base}_{lang}", "") or ""
        if value:
            return value
        return getattr(self, f"{base}_uz", "") or ""

    def localized_building(self, lang: str) -> str:
        return self._localized_part("building", lang)

    def localized_area(self, lang: str) -> str:
        return self._localized_part("area", lang)

    def display(self, lang: str = "uz") -> str:
        return f"{self.localized_building(lang)} — {self.localized_area(lang)}"

    def __str__(self):
        return self.display("uz")


class Category(TranslatableName):
    """Item category with its retention policy (days an item may stay in storage)."""

    name_uz = models.CharField(max_length=50, unique=True)
    emoji = models.CharField(max_length=10)
    retention_days = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["name_uz"]

    def save(self, *args, **kwargs):
        self._autofill_name()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.emoji} {self.localized_name('uz')}"


class Color(TranslatableName):
    """Fixed colour reference table used for consistent tagging and matching."""

    name_uz = models.CharField(max_length=32, unique=True)
    name_en = models.CharField(max_length=32, blank=True)
    name_ru = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["name_uz"]

    def save(self, *args, **kwargs):
        self._autofill_name()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.localized_name("uz")
