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


def language_menu(current: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for code in ("uz", "ru", "en"):
        label = t(code, f"lang_{code}")
        marked = f"✅ {label}" if (not current or code == current) else label
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
