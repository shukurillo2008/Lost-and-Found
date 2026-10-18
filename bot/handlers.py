"""Command handlers and the catch-all fallback router."""
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from bot_app.models import TelegramUser

from .keyboards import language_menu, main_menu
from .strings import SUPPORTED_LANGUAGES, t
from .wizards import resume_after_language_change


router = Router()
fallback_router = Router()


def _menu_text(lang: str, display_name: str) -> str:
    return f"{t(lang, 'main_menu_title').format(name=display_name)}\n\n{t(lang, 'hint_settings')}"


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, django_user: TelegramUser, is_new_user: bool = False):
    if is_new_user:
        await message.answer(
            t(django_user.language, "choose_language"),
            reply_markup=language_menu(current=None),
        )
        return
    await state.clear()
    lang = django_user.language
    await message.answer(_menu_text(lang, django_user.display_name), reply_markup=main_menu(lang))


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext, django_user: TelegramUser):
    lang = django_user.language
    prompt = t(lang, "settings_title")
    if await state.get_state() is not None:
        # Wizard in progress: keep the data; the interface language above
        # stays switchable without restarting the wizard.
        prompt = f"{prompt}\n\n{t(lang, 'settings_wizard_hint')}"
    await message.answer(prompt, reply_markup=language_menu(current=lang))


@router.callback_query(F.data.startswith("setlang:"))
async def cb_set_language(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    code = call.data.split(":", 1)[1]
    if code not in SUPPORTED_LANGUAGES:
        await call.answer()
        return

    await sync_to_async(lambda: TelegramUser.objects.filter(pk=django_user.pk).update(language=code))()
    django_user.language = code

    if call.message is not None:
        await call.message.edit_text(t(code, "language_changed"))
        resumed = await resume_after_language_change(call.message, state, code)
        if not resumed:
            await call.message.answer(_menu_text(code, django_user.display_name), reply_markup=main_menu(code))
    await call.answer()


@fallback_router.message(F.text & StateFilter(None))
async def unknown_fallback(message: Message, django_user: TelegramUser):
    lang = django_user.language
    await message.answer(
        f"{t(lang, 'fallback')}\n\n{t(lang, 'main_menu_title').format(name=django_user.display_name)}",
        reply_markup=main_menu(lang),
    )
