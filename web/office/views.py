"""Office staff web interface (Milestone 5).

All page logic lives directly inside view functions (no forms.py).
Pages are filled in one mini-milestone at a time; every page has a stub
upfront so the URL config resolves from day one.
"""
import csv
import json
import re
import urllib.request
from datetime import timedelta
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import check_for_language, gettext as _
from django.views.static import serve as static_serve

from catalog.models import Category, Color, Location
from matching.models import Handover, MatchSuggestion
from reports.models import FoundReport, LostReport
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


_MAX_PHOTO_BYTES = 5 * 1024 * 1024


def _next_free_shelf_code() -> str:
    """Prepopulate the next free shelf code: highest row+serial onward.

    Codes follow ``ROW-NN`` (e.g. A1-01); the suggestion continues the
    highest serial in the lexicographically greatest occupied row, and
    skips codes that already exist.
    """
    best = None
    for code in StoredItem.objects.values_list("shelf_code", flat=True):
        matched = re.fullmatch(r"([A-Z]+\d*)-(\d+)", code)
        if matched:
            candidate = (matched.group(1), int(matched.group(2)))
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return "A1-01"

    row, number = best
    next_number = number + 1 if number < 99 else 1
    proposed = f"{row}-{next_number:02d}"
    while StoredItem.objects.filter(shelf_code=proposed).exists() and next_number < 99:
        next_number += 1
        proposed = f"{row}-{next_number:02d}"
    return proposed


def _found_report_choices(lang: str) -> list:
    """Found reports that can still be shelved: physically handed to the
    office and not yet linked to a stored item."""
    reports = (
        FoundReport.objects.filter(custody="handed_to_office", stored_item__isnull=True)
        .select_related("reporter")
        .order_by("-created_at")[:100]
    )
    return [
        (
            report.pk,
            "#{0} · {1} ({2:%d.%m.%Y})".format(
                report.pk, report.title_in(lang), report.date_found
            ),
        )
        for report in reports
    ]


def _fetch_telegram_file(file_id: str) -> bytes | None:
    """Download a Telegram file by ``file_id`` through the Bot API.

    Report photos live on Telegram's servers; only their ``file_id``
    reference is stored locally. Returns the raw bytes, or None when the
    token/file is unavailable (the caller decides the fallback).
    """
    token = settings.BOT_TOKEN
    if not token or not file_id:
        return None
    try:
        info_request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getFile",
            data=json.dumps({"file_id": file_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(info_request, timeout=10) as response:
            info = json.loads(response.read().decode())
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        with urllib.request.urlopen(
            f"https://api.telegram.org/file/bot{token}/{file_path}", timeout=15
        ) as response:
            return response.read()
    except (OSError, ValueError):
        return None


def _report_photo_bytes(kind: str, report_id: int) -> bytes | None:
    """Photo bytes for a lost/found report: cached under MEDIA_ROOT after
    the first Bot API download, so later loads never touch Telegram."""
    cache_path = Path(settings.MEDIA_ROOT) / "report_photos" / f"{kind}-{report_id}.jpg"
    if cache_path.exists():
        return cache_path.read_bytes()
    model = {"found": FoundReport, "lost": LostReport}.get(kind)
    if model is None:
        return None
    file_id = (
        model.objects.filter(pk=report_id)
        .values_list("photo_file_id", flat=True)
        .first()
    )
    if not file_id:
        return None
    content = _fetch_telegram_file(file_id)
    if content is None:
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(content)
    return content


@staff_required
def report_photo(request: HttpRequest, kind: str, report_id: int) -> HttpResponse:
    """Bridge that shows report photos (stored on Telegram by file_id).

    Serves the cached copy after the first download; staff-only like the
    rest of the office UI.
    """
    content = _report_photo_bytes(kind, report_id)
    if content is None:
        raise Http404
    return HttpResponse(content, content_type="image/jpeg")


@staff_required
def storage_receive(request: HttpRequest) -> HttpResponse:
    """Requirement 3 — Receive item fast-entry form.

    Optional found-report link (which prefills title/description/category/
    color through ``storage_receive_prefill``), category, color, title,
    description, photo upload and a prepopulated *next free shelf code*
    suggestion. "Save & register" creates the StoredItem + the first
    ItemStatusLog entry; linking an open found report marks it registered.
    All parsing/validation lives here (no forms.py); on validation errors
    the form re-renders with the error list and submitted values.
    """
    lang = _ui_lang(request)

    base_context = {
        "found_report_choices": _found_report_choices(lang),
        "category_choices": [
            (cat.pk, cat.localized_name(lang))
            for cat in Category.objects.order_by("name_uz")
        ],
        "color_choices": [
            (clr.pk, clr.localized_name(lang))
            for clr in Color.objects.order_by("name_uz")
        ],
    }

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()
        shelf_code = (request.POST.get("shelf_code") or "").strip()
        category_id = request.POST.get("category") or ""
        color_id = request.POST.get("color") or ""
        found_report_id = request.POST.get("found_report") or ""
        photo = request.FILES.get("photo")

        errors = []
        if not title:
            errors.append(_("Title is required."))
        elif len(title) > 120:
            errors.append(_("Title is too long (max 120 characters)."))
        if not description:
            errors.append(_("Description is required."))
        if not shelf_code:
            errors.append(_("Shelf code is required."))
        elif len(shelf_code) > 16:
            errors.append(_("Shelf code is too long (max 16 characters)."))

        category = None
        if category_id.isdigit() and (found := Category.objects.filter(pk=int(category_id)).first()):
            category = found
        if category is None:
            errors.append(_("Choose a category."))

        color = None
        if color_id.isdigit() and (found := Color.objects.filter(pk=int(color_id)).first()):
            color = found
        if color is None:
            errors.append(_("Choose a color."))

        if photo and photo.size > _MAX_PHOTO_BYTES:
            errors.append(_("Photo must be at most 5 MB."))

        if shelf_code and StoredItem.objects.filter(
            status="in_storage", shelf_code=shelf_code
        ).exists():
            errors.append(_("Shelf code is already occupied."))

        found_report = None
        if found_report_id.isdigit():
            found_report = FoundReport.objects.filter(pk=int(found_report_id)).first()
            if found_report and StoredItem.objects.filter(found_report_id=found_report.pk).exists():
                errors.append(_("That found report is already linked to a stored item."))
                found_report = None

        if errors:
            return render(request, "storage/receive_form.html", {
                **base_context,
                "suggested_shelf": _next_free_shelf_code(),
                "error": " ".join(errors),
                "submitted": {
                    "title": title,
                    "description": description,
                    "shelf_code": shelf_code,
                    "category": category_id,
                    "color": color_id,
                    "found_report": found_report_id,
                },
            })

        item = StoredItem(
            title=title,
            description=description,
            category=category,
            color=color,
            shelf_code=shelf_code,
            received_by=request.user,
        )
        if found_report:
            item.found_report = found_report
        if photo:
            item.photo = photo
        item.save()  # auto_now_add received_at + retention from the category

        ItemStatusLog.objects.create(
            item=item,
            old_status="in_storage",
            new_status="in_storage",
            staff=request.user,
            note=_("Item registered."),
        )
        # Auto-copy: a linked report's photo (Telegram file_id) becomes the
        # item's own stored photo; on failure staff can still upload manually.
        if found_report and found_report.photo_file_id and not item.photo:
            report_bytes = _fetch_telegram_file(found_report.photo_file_id)
            if report_bytes:
                item.photo.save(
                    f"from-report-{found_report.pk}.jpg",
                    ContentFile(report_bytes),
                    save=False,
                )
                item.save()
            else:
                messages.warning(
                    request,
                    _("Couldn't copy the report photo — upload it manually."),
                )
        if found_report and found_report.status == "open":
            found_report.status = "registered"
            found_report.save()

        messages.success(request, _("Item registered."))
        return redirect("storage_item_detail", item_id=item.pk)

    return render(request, "storage/receive_form.html", {
        **base_context,
        "suggested_shelf": _next_free_shelf_code(),
    })


@staff_required
def storage_receive_prefill(request: HttpRequest, report_id: int) -> JsonResponse:
    """JSON payload for the receive page's found-report selector.

    Consumed by the page's vanilla JS on selection change: fills the
    title/description/category/color inputs AND populates the report
    details card (no forms.py, no JS frameworks — a plain GET endpoint).
    """
    lang = _ui_lang(request)
    report = get_object_or_404(
        FoundReport.objects.select_related("category", "color", "location", "reporter"),
        pk=report_id,
    )
    found_status_labels = {
        "open": _("Open"),
        "registered": _("Registered"),
        "returned": _("Returned"),
        "cancelled": _("Cancelled"),
    }
    return JsonResponse({
        "title": report.title_in(lang),
        "description": report.description,
        "category": report.category_id,
        "color": report.color_id,
        # The title is kept in three language streams — show all of them
        "title_uz": report.title_in("uz"),
        "title_en": report.title_in("en"),
        "title_ru": report.title_in("ru"),
        "description_uz": report.description_in("uz"),
        "description_en": report.description_in("en"),
        "description_ru": report.description_in("ru"),
        # Display-only extras for the report details card
        "category_name": report.category.localized_name(lang),
        "color_name": report.color.localized_name(lang) if report.color else "",
        "location_name": report.location.display(lang),
        "date_found": report.date_found.strftime("%d.%m.%Y"),
        "custody": _(report.get_custody_display()),
        "status_label": found_status_labels.get(report.status, report.status),
        "reporter": report.reporter.display_name,
        "finder_contact_allowed": report.finder_contact_allowed,
        "created_at": timezone.localtime(report.created_at).strftime("%d.%m.%Y %H:%M"),
        "photo_url": (
            reverse("report_photo", kwargs={"kind": "found", "report_id": report.pk})
            if report.photo_file_id
            else ""
        ),
    })


@staff_required
def media_file(request: HttpRequest, file_path: str) -> HttpResponse:
    """Serve user-uploaded media (item photos) to staff only.

    Whitenoise serves hashed STATIC assets only; media lives outside
    STATIC_ROOT, so the office panel fetches it through this gated view
    (django's serve() guards against path traversal).
    """
    return static_serve(request, file_path, document_root=str(settings.MEDIA_ROOT))


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
    """Requirement 6 — the handover act (return an item to its owner).

    A return must record WHO took the item, so the form captures the
    receiver's full name plus the last 4 digits of their ID document
    (kept only in the confidential Handover record — never on the item,
    its log or the reports). A successful save flips the item to
    ``returned``, writes the audit entry and closes the linked found
    report — and the matched lost claim, when one was confirmed.
    """
    item = get_object_or_404(
        StoredItem.objects.select_related(
            "category", "color", "received_by",
            "found_report", "found_report__reporter",
        ),
        pk=item_id,
    )
    if item.status != "in_storage" or hasattr(item, "handover"):
        messages.warning(request, _("Only items in storage can be handed over."))
        return redirect("storage_item_detail", item_id=item.pk)

    # An identity claim confirmed in match review pre-resolves the receiver
    # (claimant of the lost report); otherwise the finder's record is used.
    claim = (
        item.match_suggestions.select_related("lost_report__reporter")
        .filter(status="confirmed")
        .order_by("-reviewed_at", "-created_at")
        .first()
    )
    claim_report = claim.lost_report if claim else None
    if claim_report is not None:
        receiver_name = claim_report.reporter.display_name
    elif item.found_report:
        receiver_name = item.found_report.reporter.display_name
    else:
        receiver_name = ""
    id_last4 = ""
    note = ""

    if request.method == "POST":
        receiver_name = (request.POST.get("receiver_name") or "").strip()
        id_last4 = (request.POST.get("id_last4") or "").strip()
        note = (request.POST.get("note") or "").strip()
        if not receiver_name:
            messages.error(request, _("Receiver name is required."))
        elif not re.fullmatch(r"[0-9]{4}", id_last4):
            messages.error(request, _(
                "Enter the last 4 digits of the receiver's ID document."
            ))
        else:
            with transaction.atomic():
                Handover.objects.create(
                    stored_item=item,
                    lost_report=claim_report,
                    receiver_name=receiver_name,
                    receiver_id_last4=id_last4,
                    staff=request.user,
                    note=note,
                )
                item.status = "returned"
                item.save()
                ItemStatusLog.objects.create(
                    item=item,
                    old_status="in_storage",
                    new_status="returned",
                    staff=request.user,
                    note=note or _("Item handed to the receiver."),
                )
                if item.found_report and item.found_report.status == "registered":
                    linked = item.found_report
                    linked.status = "returned"
                    linked.save()
                if claim_report and claim_report.status in ("open", "matched"):
                    claim_report.status = "returned"
                    claim_report.save()
            messages.success(request, _("Item returned to the receiver."))
            return redirect("storage_item_detail", item_id=item.pk)

    lang = _ui_lang(request)
    labels = _status_labels()
    linked = item.found_report
    report_streams = (
        {
            "uz": linked.title_in("uz"),
            "en": linked.title_in("en"),
            "ru": linked.title_in("ru"),
        }
        if linked
        else {}
    )
    if claim_report is not None:
        reporter_name = claim_report.reporter.display_name
    elif linked:
        reporter_name = linked.reporter.display_name
    else:
        reporter_name = ""

    return render(request, "storage/handover_form.html", {
        "item": item,
        "status_label": labels.get(item.status, item.status),
        "category_name": item.category.localized_name(lang),
        "color_name": item.color.localized_name(lang),
        "report_streams": report_streams,
        "reporter_name": reporter_name,
        "has_prefill": bool(receiver_name),
        "receiver_name": receiver_name,
        "id_last4": id_last4,
        "note": note,
        "back_url": reverse("storage_item_detail", args=[item.pk]),
    })


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
