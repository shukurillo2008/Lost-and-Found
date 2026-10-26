"""Office staff web interface (Milestone 5).

All page logic lives directly inside view functions (no forms.py).
Pages are filled in one mini-milestone at a time; every page has a stub
upfront so the URL config resolves from day one.
"""
import csv
import re
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import check_for_language, gettext as _

from catalog.models import Category, Location
from matching.models import Handover, MatchSuggestion
from reports.models import LostReport
from storage.models import ItemStatusLog, StoredItem


# ---------------------------------------------------------------------------
# Access control for the whole office UI
# ---------------------------------------------------------------------------

def staff_required(view_func):
    """Gate behind BOTH login and staff status (all office pages).

    Anonymous visitors are sent to the login screen with a ``?next=``
    round-trip (validated by ``login_page`` — no open redirects);
    authenticated non-staff get a branded 403 instead of a redirect loop.
    Login, logout and language switching stay deliberately open.
    """
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("login_page"))
        if not request.user.is_staff:
            raise PermissionDenied(_("You need office staff rights to open this page."))
        return view_func(request, *args, **kwargs)
    return _wrapped


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def login_page(request: HttpRequest) -> HttpResponse:
    """Office staff login — simple function view, no forms.py."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    error = ""
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not user.is_staff:
                error = _("This account is not allowed to use the office panel.")
            else:
                login(request, user)
                next_url = request.GET.get("next") or ""
                if next_url and not url_has_allowed_host_and_scheme(
                    next_url, allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    next_url = ""
                return redirect(next_url or reverse("dashboard"))
        else:
            error = _("Invalid username or password. Try again or contact the office administrator.")
    return render(request, "accounts/login.html", {"error": error})


def logout_view(request: HttpRequest) -> HttpResponse:
    """Log the staff member out and return to the login page."""
    if request.method == "POST":
        logout(request)
        return redirect("login_page")
    return redirect("login_page")


def switch_language(request: HttpRequest, code: str) -> HttpResponse:
    """Persist the chosen interface language (uz/ru/en) and come back."""
    if check_for_language(code):
        response = redirect(request.headers.get("referer") or reverse("dashboard"))
        request.session["office_language"] = code
        response.set_cookie("office_language", code, max_age=365 * 24 * 3600)
        return response
    return redirect("storage_item_list")


# ---------------------------------------------------------------------------
# Main dashboard (requirement 2 of the M5 web UI brief)
# ---------------------------------------------------------------------------

@staff_required
def dashboard_page(request: HttpRequest) -> HttpResponse:
    """Staff dashboard: five key metrics + two charts (Chart.js placeholders).

    All aggregation happens here (no forms.py); templates render only.
    Chart data reaches the page as JSON via the ``json_script`` filter.
    """
    lang = getattr(request, "LANGUAGE_CODE", "uz") or "uz"
    if lang not in ("uz", "ru", "en"):
        lang = "uz"

    today = timezone.localdate()

    # --- Metric cards -----------------------------------------------------
    active_items = StoredItem.objects.filter(status="in_storage")
    expiring = active_items.filter(retention_until__lte=today + timedelta(days=7)).count()
    open_reports = LostReport.objects.filter(status="open").count()
    pending_matches = MatchSuggestion.objects.filter(status="suggested").count()
    returned_month = Handover.objects.filter(
        handed_at__month=today.month, handed_at__year=today.year
    ).count()

    storage_url = reverse("storage_item_list")
    reports_url = reverse("reports_lost_list")
    matches_url = reverse("reports_match_review")

    metrics = [
        {"label": _("Items in storage"), "value": active_items.count(),
         "icon": "ti-archive", "href": storage_url},
        {"label": _("Expiring within 7 days"), "value": expiring,
         "icon": "ti-alarm", "href": f"{storage_url}?filter=expiring"},
        {"label": _("Open lost reports"), "value": open_reports,
         "icon": "ti-flag", "href": reports_url},
        {"label": _("Pending match suggestions"), "value": pending_matches,
         "icon": "ti-puzzle", "href": matches_url},
        {"label": _("Items returned this month"), "value": returned_month,
         "icon": "ti-arrow-back-up", "href": f"{storage_url}?filter=returned"},
    ]

    # --- Doughnut: items in storage grouped by category --------------------
    category_counts = {
        row["category_id"]: row["total"]
        for row in active_items.values("category_id").annotate(total=Count("id"))
    }
    category_rows = []
    for cat in Category.objects.all():  # canonical order; label in UI language
        total = category_counts.get(cat.pk, 0)
        if total:
            category_rows.append({"label": cat.localized_name(lang), "value": total})

    # --- Horizontal bar: top 10 locations of lost reports ------------------
    top_locations = (
        LostReport.objects.exclude(status="cancelled")
        .filter(location__isnull=False)
        .values("location_id")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )
    locations = {
        row.pk: row
        for row in Location.objects.filter(
            pk__in=[entry["location_id"] for entry in top_locations]
        )
    }
    location_rows = [
        {
            "label": locations[entry["location_id"]].display(lang),
            "value": entry["total"],
        }
        for entry in top_locations
    ]

    return render(request, "dashboard/dashboard.html", {
        "metrics": metrics,
        "category_rows": category_rows,
        "category_chart": {
            "labels": [row["label"] for row in category_rows],
            "values": [row["value"] for row in category_rows],
        },
        "location_rows": location_rows,
        "location_chart": {
            "labels": [row["label"] for row in location_rows],
            "values": [row["value"] for row in location_rows],
        },
    })


# ---------------------------------------------------------------------------
# Storage pages (requirement 4 of the M5 web UI brief + CSV export)
# ---------------------------------------------------------------------------

def _ui_lang(request: HttpRequest) -> str:
    """Active interface language restricted to the supported set."""
    lang = getattr(request, "LANGUAGE_CODE", "uz") or "uz"
    return lang if lang in ("uz", "ru", "en") else "uz"


def _status_labels() -> dict:
    """Translated labels for StoredItem statuses.

    The choice tuples in models stay untranslated so migrations keep
    matching exactly; translation happens here at render time only.
    """
    return {
        "in_storage": _("In storage"),
        "returned": _("Returned"),
        "disposed": _("Disposed"),
        "transferred": _("Transferred"),
    }


@staff_required
def storage_receive(request: HttpRequest) -> HttpResponse:
    return render(request, "storage/receive_form.html", {})


@staff_required
def storage_item_list(request: HttpRequest) -> HttpResponse:
    """Storage inventory — dense filterable table (list view).

    GET parameters: q, status, category, shelf, received, expiring, page.
    Dashboard cards deep-link here with ?filter=expiring / ?filter=returned.
    All parsing happens inside this view (no forms.py); the template
    renders only what the "rows" list contains.
    """
    lang = _ui_lang(request)
    today = timezone.localdate()

    status = request.GET.get("status") or ""
    dashboard_filter = request.GET.get("filter") or ""
    if dashboard_filter == "returned" and not status:
        status = "returned"
    if status not in ("in_storage", "returned", "disposed", "transferred", "all"):
        status = "in_storage"

    expiring_on = bool(request.GET.get("expiring"))
    if dashboard_filter == "expiring" and not request.GET.get("status"):
        expiring_on = True

    query = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category") or ""
    shelf = (request.GET.get("shelf") or "").strip()
    received = request.GET.get("received") or ""

    items = StoredItem.objects.select_related("category", "color", "received_by", "found_report")
    if status != "all":
        items = items.filter(status=status)

    if query:
        items = items.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(shelf_code__icontains=query)
        )
    if category_id.isdigit():
        items = items.filter(category_id=int(category_id))
    if shelf:
        items = items.filter(shelf_code=shelf)
    if received == "today":
        items = items.filter(received_at__date=today)
    elif received == "week":
        items = items.filter(received_at__date__gte=today - timedelta(days=7))
    elif received == "month":
        items = items.filter(received_at__date__gte=today.replace(day=1))
    if expiring_on:
        items = items.filter(retention_until__lte=today + timedelta(days=7))

    items = items.order_by("-received_at")

    paginator = Paginator(items, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    week_ahead = today + timedelta(days=7)
    labels = _status_labels()
    rows = [
        {
            "item": item,
            "status_label": labels[item.status],
            "expiring": item.status == "in_storage" and item.retention_until <= week_ahead,
            "category_name": item.category.localized_name(lang),
            "color_name": item.color.localized_name(lang),
        }
        for item in page_obj
    ]

    params = request.GET.copy()
    if "page" in params:
        del params["page"]
    qstring = f"{params.urlencode()}&" if params else ""

    return render(request, "storage/item_list.html", {
        "rows": rows,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "has_filters": bool(query or category_id or shelf or received or expiring_on or status != "in_storage"),
        "status": status,
        "query": query,
        "expiring_on": expiring_on,
        "received": received,
        "selected_category": category_id,
        "selected_shelf": shelf,
        "category_choices": [
            (cat.pk, cat.localized_name(lang))
            for cat in Category.objects.order_by("name_uz")
        ],
        "shelves": StoredItem.objects.values_list("shelf_code", flat=True).distinct().order_by("shelf_code")[:100],
        "export_url": reverse("storage_export_csv"),
    })


@staff_required
def storage_export_csv(request: HttpRequest) -> HttpResponse:
    """Requirement 8 — "Export Monthly Inventory (CSV)".

    Exports every item RECEIVED in the chosen month (default: current one),
    regardless of its current status, with a status column. Headers follow
    the interface language; the file is UTF-8 with a BOM so Excel opens it
    correctly, and the file name carries the month it covers.
    """
    lang = _ui_lang(request)
    today = timezone.localdate()

    normalized = request.GET.get("month") or today.strftime("%Y-%m")
    matched = re.fullmatch(r"(\d{4})-(\d{1,2})", normalized)
    year, month = int(matched.group(1)), int(matched.group(2))
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        year, month = today.year, today.month

    items = (
        StoredItem.objects.filter(received_at__year=year, received_at__month=month)
        .select_related("category", "color")
        .order_by("received_at")
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="inventory-{year:04d}-{month:02d}.csv"'
    )
    response.write("\ufeff")  # BOM so Excel detects UTF-8
    writer = csv.writer(response)
    writer.writerow([
        _("Shelf"), _("Title"), _("Category"), _("Color"),
        _("Received date"), _("Retention until"), _("Status"),
    ])
    labels = _status_labels()
    for item in items:
        writer.writerow([
            item.shelf_code,
            item.title,
            item.category.localized_name(lang),
            item.color.localized_name(lang),
            item.received_at.strftime("%d.%m.%Y"),
            item.retention_until.strftime("%d.%m.%Y"),
            labels[item.status],
        ])
    return response


@staff_required
def storage_item_detail(request: HttpRequest, item_id: int) -> HttpResponse:
    """Item detail — split layout (requirement 4, detail view).

    Left card: photo + basic details. Right column: status history timeline
    (ItemStatusLog audit trail) and the Match Suggestions block. The three
    action buttons: "Return" jumps to the handover form (requirement 6 — a
    return must record the receiver, so it is not a bare status switch),
    "Dispose" and "Transfer" open confirm modals and POST ``action`` here.

    POST handling (dispose/transfer): guards — only in-storage items can
    change; the note is mandatory — then saves the new status and writes an
    ItemStatusLog entry attributed to the acting staff member.
    """
    item = get_object_or_404(
        StoredItem.objects.select_related("category", "color", "received_by", "found_report__reporter"),
        pk=item_id,
    )

    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action in ("dispose", "transfer") and item.status == "in_storage":
            note = (request.POST.get("note") or "").strip()
            if not note:
                messages.error(request, _("Note is required for this action."))
            else:
                new_status = "disposed" if action == "dispose" else "transferred"
                old_status = item.status
                item.status = new_status
                item.save()
                ItemStatusLog.objects.create(
                    item=item, old_status=old_status, new_status=new_status,
                    staff=request.user, note=note,
                )
                messages.success(
                    request,
                    _("Item marked as transferred.")
                    if action == "transfer"
                    else _("Item marked as disposed."),
                )
        else:
            messages.error(request, _("Only items in storage can be disposed or transferred."))
        return redirect("storage_item_detail", item_id=item.pk)

    lang = _ui_lang(request)
    labels = _status_labels()
    today = timezone.localdate()

    timeline = [
        {
            "old_status": entry.old_status,
            "new_status": entry.new_status,
            "from": labels.get(entry.old_status, entry.old_status),
            "to": labels.get(entry.new_status, entry.new_status),
            "staff": entry.staff.get_username(),
            "note": entry.note,
            "created_at": entry.created_at,
        }
        for entry in item.status_logs.select_related("staff")
    ]

    suggestions = [
        {
            "score": suggestion.score,
            "report_title": suggestion.lost_report.title_in(lang),
            "created_at": suggestion.created_at,
        }
        for suggestion in item.match_suggestions.select_related("lost_report")
    ]

    return render(request, "storage/item_detail.html", {
        "item": item,
        "status_label": labels.get(item.status, item.status),
        "is_expiring": item.status == "in_storage" and item.retention_until <= today + timedelta(days=7),
        "is_expired": item.status == "in_storage" and item.retention_until < today,
        "category_name": item.category.localized_name(lang),
        "color_name": item.color.localized_name(lang),
        "found_report_title": item.found_report.title_in(lang) if item.found_report else "",
        "timeline": timeline,
        "suggestions": suggestions,
        "match_review_url": reverse("reports_match_review"),
    })


@staff_required
def storage_handover(request: HttpRequest, item_id: int) -> HttpResponse:
    return render(request, "storage/handover_form.html", {"item_id": item_id})


# ---------------------------------------------------------------------------
# Reports pages (placeholders until their mini milestone)
# ---------------------------------------------------------------------------

@staff_required
def reports_lost_list(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/lost_list.html", {})


@staff_required
def reports_match_review(request: HttpRequest) -> HttpResponse:
    return render(request, "reports/match_review.html", {})


# ---------------------------------------------------------------------------
# Catalog pages (placeholders until their mini milestone)
# ---------------------------------------------------------------------------

@staff_required
def catalog_location_form(request: HttpRequest, location_id: int | None = None) -> HttpResponse:
    return render(request, "catalog/location_form.html", {"location_id": location_id})


@staff_required
def catalog_category_form(request: HttpRequest, category_id: int | None = None) -> HttpResponse:
    return render(request, "catalog/category_form.html", {"category_id": category_id})
