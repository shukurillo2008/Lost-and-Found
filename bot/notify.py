"""Reporter answers to "is this yours?" inline buttons.

The office side sends the suggestion message (``bot_app.notifications``);
this router receives the Yes/No callback, applies the decision through
the same shared service the office UI uses, and replies in the reporter's
language.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async

from bot_app.models import TelegramUser
from bot_app.notifications import (
    CONFIRM_PREFIX,
    OUTCOME_ALREADY,
    OUTCOME_CONFIRMED,
    OUTCOME_NOT_FOUND,
    OUTCOME_NOT_YOURS,
    OUTCOME_REJECTED,
    OUTCOME_REOPENED,
    REJECT_PREFIX,
    REOPEN_PREFIX,
    decide_from_bot,
    reopen_from_bot,
)

from .strings import t

logger = logging.getLogger("bot.notify")
router = Router()

RESULT_KEYS = {
    OUTCOME_CONFIRMED: "n_confirmed",
    OUTCOME_REJECTED: "n_rejected",
    OUTCOME_ALREADY: "n_already",
    OUTCOME_NOT_FOUND: "n_gone",
    OUTCOME_NOT_YOURS: "n_not_yours",
}

REOPEN_KEYS = {
    OUTCOME_REOPENED: "n_reopened",
    OUTCOME_ALREADY: "n_reopen_already",
    OUTCOME_NOT_FOUND: "n_reopen_gone",
    OUTCOME_NOT_YOURS: "n_reopen_not_yours",
}


def _callback_id(data: str) -> int:
    return int(data.split(":", 1)[1])


async def _apply(call: CallbackQuery, django_user: TelegramUser, action: str):
    lang = django_user.language
    try:
        suggestion_id = _callback_id(call.data or "")
    except (IndexError, ValueError):
        await call.answer()
        return

    outcome = await sync_to_async(decide_from_bot)(django_user, suggestion_id, action)
    message_key = RESULT_KEYS.get(outcome, "n_already")
    result_text = t(lang, message_key)

    # Any final answer makes the Yes/No buttons stale; drop them so the
    # reporter cannot press the other option by accident.
    if outcome != OUTCOME_NOT_YOURS and call.message is not None:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:  # message too old / already edited — ignore
            logger.debug("could not clear the suggestion keyboard", exc_info=True)

    await call.answer(
        result_text,
        show_alert=outcome == OUTCOME_NOT_YOURS,
    )
    if outcome in (OUTCOME_CONFIRMED, OUTCOME_REJECTED) and call.message is not None:
        await call.message.answer(result_text)


@router.callback_query(F.data.startswith(CONFIRM_PREFIX))
async def suggestion_confirmed(call: CallbackQuery, django_user: TelegramUser):
    await _apply(call, django_user, "confirm")


@router.callback_query(F.data.startswith(REJECT_PREFIX))
async def suggestion_rejected(call: CallbackQuery, django_user: TelegramUser):
    await _apply(call, django_user, "reject")


@router.callback_query(F.data.startswith(REOPEN_PREFIX))
async def report_reopened(call: CallbackQuery, django_user: TelegramUser):
    lang = django_user.language
    try:
        report_id = _callback_id(call.data or "")
    except (IndexError, ValueError):
        await call.answer()
        return

    outcome = await sync_to_async(reopen_from_bot)(django_user, report_id)
    result_text = t(lang, REOPEN_KEYS.get(outcome, "n_reopen_already"))

    if outcome != OUTCOME_NOT_YOURS and call.message is not None:
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:  # message too old / already edited — ignore
            logger.debug("could not clear the reopen keyboard", exc_info=True)

    await call.answer(
        result_text,
        show_alert=outcome == OUTCOME_NOT_YOURS,
    )
    if outcome == OUTCOME_REOPENED and call.message is not None:
        await call.message.answer(result_text)
