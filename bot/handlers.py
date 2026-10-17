"""Command and menu handlers."""
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from bot_app.models import TelegramUser

from .keyboards import (
    LANGUAGE_CALLBACK_PREFIX,
    MENU_ACTION_PREFIXES,
    language_menu,
    main_menu,
)
from .strings import SUPPORTED_LANGUAGES, t

router = Router()


def _menu_text(lang: str, display_name: str) -> str:
    return f"{t(lang, 'main_menu_title').format(name=display_name)}\n\n{t(lang, 'hint_settings')}"


@router.message(Command("start"))
async def cmd_start(message: Message, django_user: TelegramUser, is_new_user: bool = False):
    if is_new_user:
        await message.answer(
            t(django_user.language, "choose_language"),
            reply_markup=language_menu(current=None),
        )
        return
    lang = django_user.language
    await message.answer(_menu_text(lang, django_user.display_name), reply_markup=main_menu(lang))


@router.message(Command("settings"))
async def cmd_settings(message: Message, django_user: TelegramUser):
    await message.answer(
        t(django_user.language, "settings_title"),
        reply_markup=language_menu(current=django_user.language),
    )


@router.callback_query(F.data.startswith(LANGUAGE_CALLBACK_PREFIX))
async def cb_set_language(call: CallbackQuery, django_user: TelegramUser):
    code = call.data.split(":", 1)[1]
    if code not in SUPPORTED_LANGUAGES:
        await call.answer()
        return

    await sync_to_async(lambda: TelegramUser.objects.filter(pk=django_user.pk).update(language=code))()
    django_user.language = code

    if call.message is not None:
        await call.message.edit_text(t(code, "language_changed"))
        await call.message.answer(_menu_text(code, django_user.display_name), reply_markup=main_menu(code))
    await call.answer()


@router.message(F.text.startswith(MENU_ACTION_PREFIXES))
async def menu_actions_placeholder(message: Message, django_user: TelegramUser):
    await message.answer(t(django_user.language, "wip_menu"))


@router.message(F.text & StateFilter(None))
async def unknown_fallback(message: Message, django_user: TelegramUser):
    await message.answer(
        f"{t(django_user.language, 'fallback')}\n\n{t(django_user.language, 'main_menu_title').format(name=django_user.display_name)}",
        reply_markup=main_menu(django_user.language),
    )
