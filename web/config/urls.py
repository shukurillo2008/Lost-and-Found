"""config URL Configuration.

Milestones 1-4 wired only the Django admin; Milestone 5 adds the office
staff web interface (accounts, dashboard, storage, reports, catalog pages)
implemented in the ``office`` app (all logic inside view functions).
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("office.urls")),
]
