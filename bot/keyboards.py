"""Keyboard builders for the bot. All labels come from strings.py."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .strings import t

LANGUAGE_CALLBACK_PREFIX = "setlang:"
MENU_ACTION_PREFIXES = ("🧳", "🎁", "🗂", "📄")

WIZ_CANCEL_CB = "wiz_cancel"
WIZ_CONFIRM_CB = "wiz_confirm"
WIZ_EDIT_CB = "wiz_edit"
SKIP_PHOTO_CB = "skippic"


def language_menu(current: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for code in ("uz", "ru", "en"):
        label = t(code, f"lang_{code}")
        marked = f"✅ {label}" if code == current else label
        rows.append(
            [InlineKeyboardButton(text=marked, callback_data=f"{LANGUAGE_CALLBACK_PREFIX}{code}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(lang, "menu_lost")), KeyboardButton(text=t(lang, "menu_found"))],
            [KeyboardButton(text=t(lang, "menu_recent")), KeyboardButton(text=t(lang, "menu_my_reports"))],
        ],
        resize_keyboard=True,
    )


def _with_cancel(lang: str, rows):
    rows.append([InlineKeyboardButton(text=t(lang, "w_cancel"), callback_data=WIZ_CANCEL_CB)])
    return rows


def categories_inline(lang: str, categories) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{cat.emoji} {cat.localized_name(lang)}", callback_data=f"setcat:{cat.id}",
        )]
        for cat in categories
    ]
    return InlineKeyboardMarkup(inline_keyboard=_with_cancel(lang, rows))


def colors_inline(lang: str, colors) -> InlineKeyboardMarkup:
    row = []
    rows = []
    for color in colors:
        row.append(InlineKeyboardButton(
            text=color.localized_name(lang), callback_data=f"setcol:{color.id}",
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=_with_cancel(lang, rows))


def buildings_inline(lang: str, building_entries) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=display, callback_data=f"setbld:{index}")]
        for index, (_key, display) in enumerate(building_entries)
    ]
    return InlineKeyboardMarkup(inline_keyboard=_with_cancel(lang, rows))


def areas_inline(lang: str, locations, optional: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=loc.localized_area(lang), callback_data=f"setarea:{loc.id}",
        )]
        for loc in locations
    ]
    if optional:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "w_no_location"), callback_data="setarea:0")]
        )
    return InlineKeyboardMarkup(inline_keyboard=_with_cancel(lang, rows))


def photo_inline(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "w_skip_photo"), callback_data=SKIP_PHOTO_CB)],
            [InlineKeyboardButton(text=t(lang, "w_cancel"), callback_data=WIZ_CANCEL_CB)],
        ]
    )


def custody_inline(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "w_custody_office"), callback_data="custody:handed_to_office")],
            [InlineKeyboardButton(text=t(lang, "w_custody_kept"), callback_data="custody:kept_by_finder")],
            [InlineKeyboardButton(text=t(lang, "w_cancel"), callback_data=WIZ_CANCEL_CB)],
        ]
    )


def consent_inline(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "w_consent_yes"), callback_data="consent:yes")],
            [InlineKeyboardButton(text=t(lang, "w_consent_no"), callback_data="consent:no")],
            [InlineKeyboardButton(text=t(lang, "w_cancel"), callback_data=WIZ_CANCEL_CB)],
        ]
    )


def summary_inline(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "w_confirm"), callback_data=WIZ_CONFIRM_CB)],
            [InlineKeyboardButton(text=t(lang, "w_edit"), callback_data=WIZ_EDIT_CB)],
            [InlineKeyboardButton(text=t(lang, "w_cancel"), callback_data=WIZ_CANCEL_CB)],
        ]
    )


EDIT_FIELDS_BASE = ("category", "title", "description", "color", "location", "date", "photo")
EDIT_FIELDS_FOUND = EDIT_FIELDS_BASE + ("custody", "consent")


def edit_steps_inline(lang: str, is_found: bool) -> InlineKeyboardMarkup:
    fields = EDIT_FIELDS_FOUND if is_found else EDIT_FIELDS_BASE
    rows = []
    row = []
    for field in fields:
        row.append(InlineKeyboardButton(text=t(lang, f"e_{field}"), callback_data=f"editf:{field}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=_with_cancel(lang, rows))


def recent_card_kb(lang: str, mine_cb: str, prev_cb: str | None = None, next_cb: str | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t(lang, "r_mine_btn"), callback_data=mine_cb)]]
    nav = []
    if prev_cb:
        nav.append(InlineKeyboardButton(text=t(lang, "r_prev"), callback_data=prev_cb))
    if next_cb:
        nav.append(InlineKeyboardButton(text=t(lang, "r_next"), callback_data=next_cb))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pick_lost_inline(lang: str, lost_reports, found_id: int) -> InlineKeyboardMarkup:
    rows = []
    for lost in lost_reports:
        label = f"{lost.title_in(lang)[:24]} ({lost.date_lost.isoformat()})"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"minepick:{found_id}:{lost.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_reports_cancel_kb(lang: str, open_lost, open_found) -> InlineKeyboardMarkup:
    rows = []
    for lost in open_lost:
        rows.append(
            [InlineKeyboardButton(
                text=t(lang, "m_cancel_btn").format(title=lost.title_in(lang)[:24]),
                callback_data=f"cnl:lost:{lost.id}",
            )]
        )
    for found in open_found:
        rows.append(
            [InlineKeyboardButton(
                text=t(lang, "m_cancel_btn").format(title=found.title_in(lang)[:24]),
                callback_data=f"cnl:found:{found.id}",
            )]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
