"""config URL Configuration.

Minimal skeleton for Milestone 1: only the Django admin is wired up.
Project apps (catalog, reports, storage, matching, staff views) register
their URLs in later milestones.
"""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
