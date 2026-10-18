"""Self-service browsing: recent found items, this-is-mine suggestions, my reports."""
import math
from datetime import timedelta
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils import timezone

from bot_app.models import TelegramUser
from matching.models import MatchSuggestion
from reports.models import FoundReport, LostReport

from .keyboards import main_menu, my_reports_cancel_kb, pick_lost_inline, recent_card_kb
from .strings import t

router = Router()

RECENT_PAGE_SIZE = 5
RECENT_WINDOW_DAYS = 30

STATUS_LABEL_KEYS = {
    "open": "st_open",
    "matched": "st_matched",
    "returned": "st_returned",
    "expired": "st_expired",
    "cancelled": "st_cancelled",
    "registered": "st_registered",
}


def status_label(lang: str, status: str) -> str:
    return t(lang, STATUS_LABEL_KEYS.get(status, "st_open"))


def _recent_queryset():
    cutoff = timezone.localdate() - timedelta(days=RECENT_WINDOW_DAYS)
    return FoundReport.objects.filter(
        status__in=("open", "registered"),
        date_found__gte=cutoff,
    ).select_related("category", "location").order_by("-created_at")


async def _send_recent_page(message: Message, lang: str, page: int):
    total = await sync_to_async(_recent_queryset().count)()
    if total == 0:
        await message.answer(t(lang, "r_empty"))
        return
    pages = max(1, math.ceil(total / RECENT_PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    queryset = _recent_queryset()
    items = await sync_to_async(list)(
        queryset[page * RECENT_PAGE_SIZE : (page + 1) * RECENT_PAGE_SIZE]
    )
    await message.answer(t(lang, "r_title").format(page=page + 1, pages=pages))
    for index, found in enumerate(items):
        caption = t(lang, "r_card").format(
            emoji=found.category.emoji,
            title=escape(found.title_in(lang)),
            location=escape(found.location.display(lang)),
            date=found.date_found.isoformat(),
        )
        mine_cb = f"mine:{found.id}"
        is_last = index == len(items) - 1
        prev_cb = f"recent:{page - 1}" if (is_last and page > 0) else None
        next_cb = f"recent:{page + 1}" if (is_last and page < pages - 1) else None
        keyboard = recent_card_kb(lang, mine_cb, prev_cb, next_cb)
        if found.photo_file_id:
            await message.answer_photo(found.photo_file_id, caption=caption, reply_markup=keyboard)
        else:
            await message.answer(caption, reply_markup=keyboard)


@router.message(F.text.startswith("🗂"))
async def show_recent(message: Message, state: FSMContext, django_user: TelegramUser):
    await state.clear()
    await _send_recent_page(message, django_user.language, page=0)


@router.callback_query(F.data.startswith("recent:"))
async def recent_page(call: CallbackQuery, django_user: TelegramUser):
    page = int(call.data.split(":", 1)[1] or 0)
    if call.message is not None:
        await _send_recent_page(call.message, django_user.language, page)
    await call.answer()


async def _create_user_suggestion(call: CallbackQuery, django_user: TelegramUser, found_id: int, lost: LostReport):
    lang = django_user.language

    def already_exists():
        return MatchSuggestion.objects.filter(
            lost_report=lost, found_report_id=found_id
        ).exists()

    if await sync_to_async(already_exists)():
        await call.message.answer(t(lang, "r_mine_dup"))
        await call.answer()
        return

    def create():
        return MatchSuggestion.objects.create(
            lost_report=lost,
            found_report_id=found_id,
            created_by="user",
            score=0,
            score_breakdown={"source": "user_button"},
            status="suggested",
        )

    await sync_to_async(create)()
    await call.message.answer(t(lang, "r_mine_created"))
    await call.answer()


@router.callback_query(F.data.startswith("mine:"))
async def claim_found_item(call: CallbackQuery, django_user: TelegramUser):
    found_id = int(call.data.split(":", 1)[1])
    lang = django_user.language

    def open_lost_reports():
        return list(
            LostReport.objects.filter(reporter=django_user, status="open").order_by("-created_at")
        )

    lost_reports = await sync_to_async(open_lost_reports)()
    if not lost_reports:
        await call.answer(t(lang, "r_mine_no_lost"), show_alert=True)
        return
    if len(lost_reports) == 1:
        await _create_user_suggestion(call, django_user, found_id, lost_reports[0])
        return
    await call.message.answer(
        t(lang, "r_mine_pick"),
        reply_markup=pick_lost_inline(lang, lost_reports, found_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("minepick:"))
async def claim_found_item_picked(call: CallbackQuery, django_user: TelegramUser):
    _, found_id, lost_id = call.data.split(":")
    found_id, lost_id = int(found_id), int(lost_id)

    def get_lost():
        return LostReport.objects.get(pk=lost_id, reporter=django_user, status="open")

    try:
        lost = await sync_to_async(get_lost)()
    except LostReport.DoesNotExist:
        await call.answer()
        return
    await _create_user_suggestion(call, django_user, found_id, lost)


@router.message(F.text.startswith("📄"))
async def show_my_reports(message: Message, state: FSMContext, django_user: TelegramUser):
    await state.clear()
    lang = django_user.language

    def fetch():
        lost = list(django_user.lost_reports.order_by("-created_at")[:10])
        found = list(django_user.found_reports.order_by("-created_at")[:10])
        return lost, found

    lost, found = await sync_to_async(fetch)()
    if not lost and not found:
        await message.answer(t(lang, "m_empty"))
        return

    sections = [t(lang, "m_title")]
    if lost:
        sections.append(t(lang, "m_lost_section"))
        sections.extend(
            t(lang, "m_line").format(
                title=escape(item.title_in(lang)),
                status=status_label(lang, item.status),
                date=item.date_lost.isoformat(),
            )
            for item in lost
        )
    if found:
        sections.append(t(lang, "m_found_section"))
        sections.extend(
            t(lang, "m_line").format(
                title=escape(item.title_in(lang)),
                status=status_label(lang, item.status),
                date=item.date_found.isoformat(),
            )
            for item in found
        )

    open_lost = [item for item in lost if item.status == "open"]
    open_found = [item for item in found if item.status == "open"]
    if open_lost or open_found:
        sections.append(t(lang, "m_cancel_hint"))
        await message.answer(
            "\n".join(sections),
            reply_markup=my_reports_cancel_kb(lang, open_lost, open_found),
        )
    else:
        sections.append(t(lang, "m_nothing_to_cancel"))
        await message.answer("\n".join(sections))


@router.callback_query(F.data.startswith("cnl:"))
async def cancel_report(call: CallbackQuery, django_user: TelegramUser):
    _, kind, report_id = call.data.split(":")
    report_id = int(report_id)
    lang = django_user.language

    def cancel():
        model = LostReport if kind == "lost" else FoundReport
        updated = model.objects.filter(
            pk=report_id, reporter=django_user, status="open"
        ).update(status="cancelled")
        return updated

    updated = await sync_to_async(cancel)()
    if updated and call.message is not None:
        await call.message.answer(t(lang, "m_cancelled"))
    await call.answer()
