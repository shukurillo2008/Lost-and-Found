from django.contrib import admin

from .models import Category, Color, Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("id", "building", "area")
    list_filter = ("building",)
    search_fields = ("building", "area")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "emoji", "name", "retention_days")
    search_fields = ("name",)


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
