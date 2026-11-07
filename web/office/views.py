"""Office staff web interface (Milestone 5).

All page logic lives directly inside view functions (no forms.py).
Pages are filled in one mini-milestone at a time; every page has a stub
upfront so the URL config resolves from day one.
"""
import csv
import json
import re
import urllib.request
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncWeek
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import check_for_language, gettext as _
from django.views.static import serve as static_serve

from catalog.models import Category, Color, Location
from matching.engine import score_breakdown, score_from_breakdown
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
    # "Expiring" = still valid today but not later than 7 days ahead;
    # overdue (already expired, awaiting disposal) must not slip in here.
    expiring = active_items.filter(
        retention_until__gte=today, retention_until__lte=today + timedelta(days=7)
    ).count()
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
         "icon": "ti-flag", "href": f"{reports_url}?status=open"},
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

    # --- Horizontal bar: storage items grouped by retention outlook --------
    # Buckets by days left until retention_until: overdue / <=7 / 8-14 /
    # 15-30 / >30. All in-storage rows participate, so the buckets always
    # sum up to the "Items in storage" metric above.
    retention_rows = [
        {"label": _("Overdue"), "value": 0, "tone": "gold"},
        {"label": _("Within 7 days"), "value": 0, "tone": "navy"},
        {"label": _("8-14 days"), "value": 0, "tone": "navy"},
        {"label": _("15-30 days"), "value": 0, "tone": "navy"},
        {"label": _("Over 30 days"), "value": 0, "tone": "navy"},
    ]
    retention_chart = {
        "labels": [row["label"] for row in retention_rows],
        "values": [row["value"] for row in retention_rows],
        "tones": [row["tone"] for row in retention_rows],
    }
    for deadline in active_items.values_list("retention_until", flat=True):
        days_left = (deadline - today).days
        if days_left < 0:
            retention_rows[0]["value"] += 1
        elif days_left <= 7:
            retention_rows[1]["value"] += 1
        elif days_left <= 14:
            retention_rows[2]["value"] += 1
        elif days_left <= 30:
            retention_rows[3]["value"] += 1
        else:
            retention_rows[4]["value"] += 1
    retention_chart["values"] = [row["value"] for row in retention_rows]

    # --- Line: storage flow over the last 8 weeks (received vs. left) ------
    this_monday = today - timedelta(days=today.weekday())
    flow_weeks = [this_monday - timedelta(weeks=offset) for offset in range(7, -1, -1)]
    received_by_week = {
        row["week"].date(): row["total"]
        for row in StoredItem.objects.annotate(week=TruncWeek("received_at"))
        .values("week")
        .annotate(total=Count("id"))
    }
    returned_by_week = {
        row["week"].date(): row["total"]
        for row in Handover.objects.annotate(week=TruncWeek("handed_at"))
        .values("week")
        .annotate(total=Count("id"))
    }
    disposed_by_week = {
        row["week"].date(): row["total"]
        for row in ItemStatusLog.objects.filter(new_status="disposed")
        .annotate(week=TruncWeek("created_at"))
        .values("week")
        .annotate(total=Count("id"))
    }
    week_rows = [
        {
            "label": week.strftime("%d.%m"),
            "received": received_by_week.get(week, 0),
            "returned": returned_by_week.get(week, 0),
            "disposed": disposed_by_week.get(week, 0),
        }
        for week in flow_weeks
    ]
    flow_chart = {
        "labels": [row["label"] for row in week_rows],
        "received": [row["received"] for row in week_rows],
        "returned": [row["returned"] for row in week_rows],
        "disposed": [row["disposed"] for row in week_rows],
        "received_label": _("Received"),
        "returned_label": _("Returned"),
        "disposed_label": _("Disposed"),
    }

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
        "retention_rows": retention_rows,
        "retention_chart": retention_chart,
        "week_rows": week_rows,
        "flow_chart": flow_chart,
    })


# ---------------------------------------------------------------------------
# Storage pages (requirement 4 of the M5 web UI brief + CSV export)
# ---------------------------------------------------------------------------

def _ui_lang(request: HttpRequest) -> str:
    """Active interface language restricted to the supported set."""
    lang = getattr(request, "LANGUAGE_CODE", "uz") or "uz"
    return lang if lang in ("uz", "ru", "en") else "uz"


_DATE_PARAM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date_param(raw: str) -> tuple:
    """Parse one optional ``date_from``/``date_to`` GET value.

    Returns ``(date, True)`` for a real date or empty input, and
    ``(None, False)`` for malformed input so the caller can flash a hint
    and silently drop the broken half of the range.
    """
    raw = (raw or "").strip()
    if not raw:
        return None, True
    if _DATE_PARAM.match(raw):
        try:
            return date.fromisoformat(raw), True
        except ValueError:
            pass
    return None, False


def _date_range_or_flash(request: HttpRequest) -> tuple:
    """Shared date-range parsing for the list filters.

    Flash + drop only the malformed value; the valid half still filters.
    """
    date_from, ok_from = _parse_date_param(request.GET.get("date_from"))
    date_to, ok_to = _parse_date_param(request.GET.get("date_to"))
    if not (ok_from and ok_to):
        messages.error(request, _("Enter dates in YYYY-MM-DD format."))
        date_from = date_from if ok_from else None
        date_to = date_to if ok_to else None
    return date_from, date_to


def _echo_range(date_from, date_to) -> dict:
    """Template echo values for the two date inputs (ISO strings)."""
    return {
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    }


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


def _lost_status_labels() -> dict:
    """Translated labels for LostReport statuses (render-time only, same
    pattern as ``_status_labels``)."""
    return {
        "open": _("Open"),
        "matched": _("Matched"),
        "returned": _("Returned"),
        "expired": _("Expired"),
        "cancelled": _("Cancelled"),
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
    date_from, date_to = _date_range_or_flash(request)

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
    # Quick presets apply only when the staff member typed no explicit
    # date range — the explicit value always wins.
    if not (date_from or date_to):
        if received == "today":
            items = items.filter(received_at__date=today)
        elif received == "week":
            items = items.filter(received_at__date__gte=today - timedelta(days=7))
        elif received == "month":
            items = items.filter(received_at__date__gte=today.replace(day=1))
    else:
        received = ""
    if date_from:
        items = items.filter(received_at__date__gte=date_from)
    if date_to:
        items = items.filter(received_at__date__lte=date_to)
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
        "qstring": qstring,
        "has_filters": bool(query or category_id or shelf or received or expiring_on
                            or date_from or date_to or status != "in_storage"),
        "status": status,
        "query": query,
        "expiring_on": expiring_on,
        "received": received,
        **_echo_range(date_from, date_to),
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
            "staff": entry.staff.get_username() if entry.staff_id else "worker",
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
    """Lost reports — filterable list (section 4.2 of the course brief).

    GET parameters: q, status, category, location, page. The dashboard
    "Open lost reports" card deep-links here with ``?status=open``.
    The listing is search-plus-filters only; all parsing lives in this
    view function (no forms.py) and the template renders ``rows``.
    """
    lang = _ui_lang(request)

    status = request.GET.get("status") or "all"
    if status not in ("open", "matched", "returned", "expired", "cancelled", "all"):
        status = "all"

    query = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category") or ""
    location_id = request.GET.get("location") or ""
    date_from, date_to = _date_range_or_flash(request)

    reports = (
        LostReport.objects.select_related("category", "color", "reporter", "location")
        .annotate(
            suggested_count=Count(
                "match_suggestions",
                filter=Q(match_suggestions__status="suggested"),
                distinct=True,
            )
        )
        .order_by("-date_lost", "-created_at")
    )
    if status != "all":
        reports = reports.filter(status=status)
    if query:
        # Search what the table can *show*: canonical text plus every
        # language stream, so a term visible on any UI language also
        # finds its report (ru visitors type the translated title).
        reports = reports.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
            | Q(title_uz__icontains=query) | Q(title_en__icontains=query)
            | Q(title_ru__icontains=query)
            | Q(description_uz__icontains=query) | Q(description_en__icontains=query)
            | Q(description_ru__icontains=query)
        )
    if category_id.isdigit():
        reports = reports.filter(category_id=int(category_id))
    if location_id.isdigit():
        reports = reports.filter(location_id=int(location_id))
    if date_from:
        reports = reports.filter(date_lost__gte=date_from)
    if date_to:
        reports = reports.filter(date_lost__lte=date_to)

    paginator = Paginator(reports, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    labels = _lost_status_labels()
    rows = [
        {
            "report": report,
            # Title/description follow the UI language exactly like the
            # category/color columns; blank streams fall back to the
            # canonical original text (title_in/description_in).
            "title_ui": report.title_in(lang),
            "description_ui": report.description_in(lang),
            "status_label": labels.get(report.status, report.status),
            "category_name": report.category.localized_name(lang),
            "color_name": report.color.localized_name(lang) if report.color else "",
            "location_name": report.location.display(lang) if report.location else "",
            "suggested_count": report.suggested_count,
        }
        for report in page_obj
    ]

    params = request.GET.copy()
    if "page" in params:
        del params["page"]
    qstring = f"{params.urlencode()}&" if params else ""

    return render(request, "reports/lost_list.html", {
        "rows": rows,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "has_filters": bool(query or category_id or location_id or date_from
                            or date_to or status != "all"),
        "status": status,
        "query": query,
        "selected_category": category_id,
        "selected_location": location_id,
        **_echo_range(date_from, date_to),
        "category_choices": [
            (cat.pk, cat.localized_name(lang))
            for cat in Category.objects.order_by("name_uz")
        ],
        "location_choices": [
            (loc.pk, loc.display(lang))
            for loc in Location.objects.order_by("building_uz", "area_uz")
        ],
    })


def _suggestion_row(suggestion: MatchSuggestion, lang: str, labels: dict) -> dict:
    """Render-ready data for ONE match suggestion row (detail page and
    review queue share the same card via ``reports/_suggestion_row.html``)."""
    criteria_pins = {
        "color": _("Same color"),
        "temporal": _("Found within 14 days"),
        "building": _("Same building"),
        "area": _("Same area"),
        "words": _("Shared words"),
    }
    decision_labels = {
        "suggested": _("Suggested"),
        "confirmed": _("Confirmed"),
        "rejected": _("Rejected"),
    }
    item = suggestion.stored_item
    breakdown = [
        {"label": criteria_pins[key], "points": suggestion.score_breakdown.get(key)}
        for key in ("color", "temporal", "building", "area", "words")
        if suggestion.score_breakdown.get(key)
    ]
    return {
        "suggestion": suggestion,
        "decision_label": decision_labels.get(suggestion.status, suggestion.status),
        "item": item,
        "item_status_label": labels.get(item.status, item.status) if item else "",
        "item_category": item.category.localized_name(lang) if item else "",
        "item_color": item.color.localized_name(lang) if item else "",
        "breakdown": breakdown,
        "shared_words": suggestion.score_breakdown.get("shared_words") or [],
    }


def _suggestion_rows(report, lang):
    """Render-ready data for the match review block of the detail page.

    Rows are ordered: pending decisions first, then confirmed, then
    rejected; each carries the numeric breakdown translated for the UI.
    """
    labels = _status_labels()
    suggestions = list(
        report.match_suggestions.select_related(
            "stored_item__category", "stored_item__color",
            "stored_item__found_report", "reviewed_by",
        )
    )
    suggestions.sort(
        key=lambda s: (
            {"suggested": 0, "confirmed": 1, "rejected": 2}.get(s.status, 3),
            -s.score,
        )
    )
    return [_suggestion_row(s, lang, labels) for s in suggestions]


def _decide_suggestion(request: HttpRequest, suggestion: MatchSuggestion, action: str) -> bool:
    """Shared staff decision for one match suggestion.

    Used by the report detail page AND the review queue, so both behave
    identically: a fresh suggestion accepts ``confirm``; rejection works
    on suggested and confirmed rows (undo of a confirmation); rejecting
    the last confirmed suggestion drops the report back to ``open``.
    Returns True when a new decision was recorded.
    """
    report = suggestion.lost_report
    if action == "confirm" and suggestion.status != "suggested":
        # Confirming twice is a no-op; only fresh suggestions confirm.
        messages.info(request, _("This suggestion was already reviewed."))
        return False
    if action == "reject" and suggestion.status == "rejected":
        messages.info(request, _("This suggestion was already reviewed."))
        return False

    suggestion.status = "confirmed" if action == "confirm" else "rejected"
    suggestion.reviewed_by = request.user
    suggestion.reviewed_at = timezone.now()
    suggestion.save()
    if action == "confirm":
        if report.status == "open":
            report.status = "matched"
            report.save()
        messages.success(request, _("Match confirmed — the handover form is pre-filled."))
    else:
        if report.status == "matched" and not report.match_suggestions.filter(
            status="confirmed"
        ).exists():
            report.status = "open"
            report.save()
        messages.success(request, _("Suggestion rejected."))
    return True


@staff_required
def reports_lost_detail(request: HttpRequest, report_id: int) -> HttpResponse:
    """Lost report detail (section 4.2): report facts with trilingual
    streams plus the review block — confirm, reject or manually pick any
    stored item as a match.

    Confirming a suggestion sets the report to ``matched``; rejecting the
    last confirmed suggestion drops it back to ``open``. A confirmed match
    pre-resolves the handover receiver (M5.8 flow). Manual picks score the
    pair via the matching engine and remember ``created_by="staff"``.
    """
    report = get_object_or_404(
        LostReport.objects.select_related("category", "color", "reporter", "location"),
        pk=report_id,
    )
    lang = _ui_lang(request)

    if request.method == "POST":
        action = request.POST.get("action") or ""

        if action in ("confirm", "reject"):
            suggestion = report.match_suggestions.filter(
                pk=request.POST.get("suggestion_id") or 0
            ).select_related("lost_report", "reviewed_by").first()
            if suggestion is None:
                messages.error(request, _("No such suggestion for this report."))
            else:
                _decide_suggestion(request, suggestion, action)
            return redirect("reports_lost_detail", report_id=report.pk)

        if action == "pick":
            if report.status not in ("open", "matched"):
                messages.error(request, _("Only open or matched reports accept new suggestions."))
            else:
                raw_id = (request.POST.get("stored_item") or "").strip()
                if not raw_id.isdigit():
                    messages.error(request, _("Choose an item from the shelf list."))
                else:
                    item = (
                        StoredItem.objects.filter(status="in_storage", pk=int(raw_id))
                        .select_related("category", "color", "found_report")
                        .first()
                    )
                    if item is None:
                        messages.error(request, _("Only items in storage can be matched."))
                    else:
                        breakdown = {"source": "staff_pick", **score_breakdown(report, item)}
                        try:
                            MatchSuggestion.objects.create(
                                lost_report=report, stored_item=item, created_by="staff",
                                score=score_from_breakdown(breakdown),
                                score_breakdown=breakdown, status="suggested",
                            )
                        except IntegrityError:
                            messages.warning(
                                request, _("This item is already suggested for the report.")
                            )
                        else:
                            messages.success(request, _("Suggestion created from the pick."))
            return redirect("reports_lost_detail", report_id=report.pk)

        messages.error(request, _("Unknown action."))
        return redirect("reports_lost_detail", report_id=report.pk)

    # ---- GET: assemble the page -----------------------------------------
    labels = _lost_status_labels()

    pick_choices = []
    if report.status in ("open", "matched"):
        existing_ids = list(report.match_suggestions.values_list("stored_item_id", flat=True))
        pick_choices = [
            (item.pk, f"{item.shelf_code} — {item.title} ({item.category.localized_name(lang)})")
            for item in StoredItem.objects.filter(status="in_storage")
            .select_related("category", "color")
            .exclude(pk__in=existing_ids)
            .order_by("shelf_code")[:100]
        ]

    return render(request, "reports/lost_detail.html", {
        "report": report,
        "status_label": labels.get(report.status, report.status),
        "category_name": report.category.localized_name(lang),
        "color_name": report.color.localized_name(lang) if report.color else "",
        "location_name": report.location.display(lang) if report.location else "",
        "reporter_name": report.reporter.display_name,
        "photo_url": reverse("report_photo", args=["lost", report.pk]) if report.photo_file_id else None,
        "title_streams": {
            code: report.title_in(code) for code in ("uz", "en", "ru")
        },
        "description_streams": {
            code: report.description_in(code) for code in ("uz", "en", "ru")
        },
        "suggestion_rows": _suggestion_rows(report, lang),
        "pick_choices": pick_choices,
        "pick_url": reverse("reports_lost_detail", args=[report.pk]),
        "back_url": reverse("reports_lost_list"),
    })


@staff_required
def reports_match_review(request: HttpRequest) -> HttpResponse:
    """Global match review queue (requirement 5).

    Defaults to the pending (``suggested``) decisions, grouped per lost
    report; the ``?status=`` filter also exposes confirmed, rejected or
    all decisions for transparency. POST applies the same confirm/reject
    semantics as the report detail page (``_decide_suggestion``) and
    redirects back to the same filter view.
    """
    lang = _ui_lang(request)

    if request.method == "POST":
        action = request.POST.get("action") or ""
        if action in ("confirm", "reject"):
            suggestion = MatchSuggestion.objects.filter(
                pk=request.POST.get("suggestion_id") or 0
            ).select_related("lost_report", "reviewed_by").first()
            if suggestion is None:
                messages.error(request, _("No such match suggestion."))
            else:
                _decide_suggestion(request, suggestion, action)
        else:
            messages.error(request, _("Unknown action."))
        return redirect(request.get_full_path())

    decision = request.GET.get("status") or "suggested"
    if decision not in ("suggested", "confirmed", "rejected", "all"):
        decision = "suggested"

    date_from, date_to = _date_range_or_flash(request)

    suggestions = MatchSuggestion.objects.select_related(
        "lost_report", "lost_report__reporter",
        "stored_item__category", "stored_item__color",
        "stored_item__found_report", "reviewed_by",
    ).order_by(
        "-lost_report__date_lost", "-lost_report__id", "-score", "-created_at"
    )
    if decision != "all":
        suggestions = suggestions.filter(status=decision)
    if date_from:
        suggestions = suggestions.filter(lost_report__date_lost__gte=date_from)
    if date_to:
        suggestions = suggestions.filter(lost_report__date_lost__lte=date_to)

    paginator = Paginator(suggestions, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    labels = _status_labels()
    lost_labels = _lost_status_labels()
    groups = []
    for suggestion in page_obj:
        report = suggestion.lost_report
        if not groups or groups[-1]["report"].pk != report.pk:
            groups.append({
                "report": report,
                "title_ui": report.title_in(lang),
                "status_label": lost_labels.get(report.status, report.status),
                "date_lost": report.date_lost,
                "reporter_name": report.reporter.display_name,
                "rows": [],
            })
        groups[-1]["rows"].append(_suggestion_row(suggestion, lang, labels))

    params = request.GET.copy()
    if "page" in params:
        del params["page"]
    qstring = f"{params.urlencode()}&" if params else ""

    return render(request, "reports/match_review.html", {
        "groups": groups,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "decision": decision,
        **_echo_range(date_from, date_to),
        "qstring": qstring,
        "post_url": request.get_full_path(),
    })


# ---------------------------------------------------------------------------
# Catalog pages (placeholders until their mini milestone)
# ---------------------------------------------------------------------------

@staff_required
def catalog_location_form(request: HttpRequest, location_id: int | None = None) -> HttpResponse:
    """Reference data — campus locations (requirement 7).

    One page does list + create/edit + delete; ``/catalog/locations/<id>/``
    opens the SAME page with the form prefilled for editing. ``building_uz``
    / ``area_uz`` are required; blank en/ru streams are auto-translated on
    save (``Location.save`` → ``apply_to_fields``). Deleting is refused
    while reports still reference the location (the FK is SET_NULL, so a
    plain delete would silently detach report history).
    """
    lang = _ui_lang(request)
    location = get_object_or_404(Location, pk=location_id) if location_id else None

    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip()

        if action == "delete":
            if location is None:
                # Row buttons POST the id with action=delete on the list URL.
                location = get_object_or_404(Location, pk=request.POST.get("location_id") or 0)
            if LostReport.objects.filter(location=location).exists():
                messages.error(
                    request, _("This location is referenced by reports and cannot be deleted.")
                )
            else:
                location.delete()
                messages.success(request, _("Location deleted."))
            return redirect("catalog_location_form")

        building = (request.POST.get("building_uz") or "").strip()
        area = (request.POST.get("area_uz") or "").strip()
        if not building or not area:
            messages.error(request, _("Building and area are required."))
        else:
            updates = {
                "building_uz": building,
                "area_uz": area,
                "building_en": (request.POST.get("building_en") or "").strip(),
                "area_en": (request.POST.get("area_en") or "").strip(),
                "building_ru": (request.POST.get("building_ru") or "").strip(),
                "area_ru": (request.POST.get("area_ru") or "").strip(),
            }
            target = location if location is not None else Location()
            for field, value in updates.items():
                setattr(target, field, value)
            try:
                target.save()
            except IntegrityError:
                messages.error(request, _("This building and area pair already exists."))
            else:
                if location is not None:
                    messages.success(request, _("Location updated."))
                else:
                    messages.success(request, _("Location created."))
                return redirect("catalog_location_form")
        return redirect("catalog_location_form")

    rows = [
        {
            "location": item,
            "building": item.localized_building(lang),
            "area": item.localized_area(lang),
            "report_count": item.report_count,
            "edit_url": reverse("catalog_location_edit", args=[item.pk]),
        }
        for item in Location.objects.annotate(
            report_count=Count("lost_reports", distinct=True)
        )
    ]
    return render(request, "catalog/location_form.html", {
        "rows": rows,
        "total_count": len(rows),
        "location": location,
        "form_url": (
            reverse("catalog_location_edit", args=[location.pk])
            if location is not None else reverse("catalog_location_form")
        ),
    })


@staff_required
def catalog_category_form(request: HttpRequest, category_id: int | None = None) -> HttpResponse:
    """Reference data — item categories AND fixed colour list (req 7).

    One page, two sections: a category tab (list + trilingual name form +
    emoji + retention_days) and a color tab (list + trilingual name form).
    ``category_id`` opens the category form prefilled for editing; colors
    are edited through ``?color=<pk>`` (prefill) + ``save_color`` POST.
    Deletes are refused while any report or stored item references the
    row (all relevant FKs are PROTECT).
    """
    lang = _ui_lang(request)
    category = get_object_or_404(Category, pk=category_id) if category_id else None

    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip()

        # ---- Colors ------------------------------------------------------
        if action in ("save_color", "delete_color"):
            if action == "delete_color":
                color = get_object_or_404(
                    Color, pk=request.POST.get("color_id") or 0
                )
                used = (
                    LostReport.objects.filter(color=color).exists()
                    or FoundReport.objects.filter(color=color).exists()
                    or StoredItem.objects.filter(color=color).exists()
                )
                if used:
                    messages.error(
                        request, _("This color is referenced by items or reports and cannot be deleted.")
                    )
                else:
                    color.delete()
                    messages.success(request, _("Color deleted."))
                return redirect("catalog_category_form")

            name = (request.POST.get("name_uz") or "").strip()
            if not name:
                messages.error(request, _("Colour name is required."))
            else:
                is_update = bool(request.POST.get("color_id"))
                updates = {
                    "name_uz": name,
                    "name_en": (request.POST.get("name_en") or "").strip(),
                    "name_ru": (request.POST.get("name_ru") or "").strip(),
                }
                target = (
                    Color.objects.get(pk=request.POST.get("color_id"))
                    if is_update else Color()
                )
                for field, value in updates.items():
                    setattr(target, field, value)
                try:
                    target.save()
                except IntegrityError:
                    messages.error(request, _("This color already exists."))
                else:
                    messages.success(
                        request, _("Color updated.") if is_update else _("Color created.")
                    )
                return redirect("catalog_category_form")

        # ---- Categories --------------------------------------------------
        if action == "delete":
            if category is None:
                # Row buttons POST the id with action=delete on the list URL.
                category = get_object_or_404(Category, pk=request.POST.get("category_id") or 0)
            used = (
                LostReport.objects.filter(category=category).exists()
                or FoundReport.objects.filter(category=category).exists()
                or StoredItem.objects.filter(category=category).exists()
            )
            if used:
                messages.error(
                    request, _("This category is referenced by items or reports and cannot be deleted.")
                )
            else:
                category.delete()
                messages.success(request, _("Category deleted."))
            return redirect("catalog_category_form")

        name = (request.POST.get("name_uz") or "").strip()
        emoji = ((request.POST.get("emoji") or "").strip() or None)
        raw_days = (request.POST.get("retention_days") or "").strip()
        if not name:
            messages.error(request, _("Category name is required."))
        elif not emoji:
            messages.error(request, _("An emoji is required."))
        elif not raw_days.isdigit() or not (1 <= int(raw_days) <= 365):
            messages.error(request, _("Retention must be a whole number of days between 1 and 365."))
        else:
            duplicate = Category.objects.filter(name_uz=name).exclude(
                pk=category.pk if category is not None else None
            )
            if duplicate.exists():
                messages.error(request, _("This category already exists."))
            else:
                updates = {
                    "name_uz": name,
                    "name_en": (request.POST.get("name_en") or "").strip(),
                    "name_ru": (request.POST.get("name_ru") or "").strip(),
                    "emoji": emoji,
                    "retention_days": int(raw_days),
                }
                target = category if category is not None else Category()
                for field, value in updates.items():
                    setattr(target, field, value)
                target.save()
                messages.success(
                    request, _("Category updated.") if category is not None
                    else _("Category created.")
                )
            return redirect("catalog_category_form")
        return redirect("catalog_category_form")

    # ---- GET: two render blocks -------------------------------------------
    color_edit = None
    raw_color = (request.GET.get("color") or "").strip()
    if raw_color.isdigit():
        color_edit = Color.objects.filter(pk=int(raw_color)).first()

    category_rows = [
        {
            "category": item,
            "name": item.localized_name(lang),
            "stored_count": item.stored_items.count(),
            "report_count": item.lost_reports.count() + item.found_reports.count(),
            "edit_url": reverse("catalog_category_edit", args=[item.pk]),
        }
        for item in Category.objects.all()
    ]
    color_rows = [
        {
            "color": item,
            "name": item.localized_name(lang),
            "usage_count": (
                item.stored_items.count() + item.lost_reports.count()
                + item.found_reports.count()
            ),
        }
        for item in Color.objects.all()
    ]
    return render(request, "catalog/category_form.html", {
        "category_rows": category_rows,
        "color_rows": color_rows,
        "total_count": len(category_rows) + len(color_rows),
        "category": category,
        "color": color_edit,
        "category_form_url": (
            reverse("catalog_category_edit", args=[category.pk])
            if category is not None else reverse("catalog_category_form")
        ),
        "color_form_url": reverse("catalog_category_form"),
    })
