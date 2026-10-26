"""URLs for the office staff web interface (Milestone 5)."""
from django.urls import path

from office import views

urlpatterns = [
    # Accounts
    path("accounts/login/", views.login_page, name="login_page"),
    path("accounts/logout/", views.logout_view, name="logout_page"),
    path("lang/<str:code>/", views.switch_language, name="switch_language"),

    # Main dashboard (requirement 2 of the M5 web UI brief)
    path("", views.dashboard_page, name="dashboard"),

    # Storage
    path("storage/", views.storage_item_list, name="storage_item_list"),
    path("storage/receive/", views.storage_receive, name="storage_receive"),
    path("storage/export/", views.storage_export_csv, name="storage_export_csv"),
    path("storage/items/<int:item_id>/", views.storage_item_detail, name="storage_item_detail"),
    path("storage/items/<int:item_id>/handover/", views.storage_handover, name="storage_handover"),

    # Reports
    path("reports/lost/", views.reports_lost_list, name="reports_lost_list"),
    path("reports/matches/", views.reports_match_review, name="reports_match_review"),

    # Catalog
    path("catalog/locations/", views.catalog_location_form, name="catalog_location_form"),
    path("catalog/locations/<int:location_id>/", views.catalog_location_form, name="catalog_location_edit"),
    path("catalog/categories/", views.catalog_category_form, name="catalog_category_form"),
    path("catalog/categories/<int:category_id>/", views.catalog_category_form, name="catalog_category_edit"),
]
