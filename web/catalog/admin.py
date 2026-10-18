from django.contrib import admin

from .models import Category, Color, Location


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "emoji", "name_uz", "name_en", "name_ru", "retention_days")
    search_fields = ("name_uz", "name_en", "name_ru")


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    list_display = ("id", "name_uz", "name_en", "name_ru")
    search_fields = ("name_uz", "name_en", "name_ru")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "building_uz", "building_en", "building_ru",
        "area_uz", "area_en", "area_ru",
    )
    list_filter = ("building_uz",)
    search_fields = (
        "building_uz", "building_en", "building_ru",
        "area_uz", "area_en", "area_ru",
    )
