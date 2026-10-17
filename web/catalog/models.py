from django.db import models


class Location(models.Model):
    """Hierarchical campus place: building + specific area inside it."""

    building = models.CharField(max_length=100)
    area = models.CharField(max_length=150)

    class Meta:
        ordering = ["building", "area"]
        constraints = [
            models.UniqueConstraint(fields=["building", "area"], name="unique_building_area"),
        ]

    def __str__(self):
        return f"{self.building} — {self.area}"


class Category(models.Model):
    """Item category with its retention policy (days an item may stay in storage)."""

    name = models.CharField(max_length=50, unique=True)
    emoji = models.CharField(max_length=10)
    retention_days = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.emoji} {self.name}"


class Color(models.Model):
    """Fixed colour reference table used for consistent tagging and matching."""

    name = models.CharField(max_length=32, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
