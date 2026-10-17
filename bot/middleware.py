"""Outer middleware: auto-creates the TelegramUser and aborts blocked users."""
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from asgiref.sync import sync_to_async

from bot_app.models import TelegramUser

from .strings import t


def _display_name(from_user) -> str:
    parts = [from_user.first_name or "", from_user.last_name or ""]
    return " ".join(part for part in parts if part).strip() or str(from_user.id)


def _get_or_create_telegram_user(from_user):
    tg_user, created = TelegramUser.objects.get_or_create(
        telegram_id=from_user.id,
        defaults={
            "username": from_user.username,
            "display_name": _display_name(from_user),
            "language": TelegramUser._meta.get_field("language").default,
        },
    )
    if not created:
        new_name = _display_name(from_user)
        updates = {}
        if tg_user.username != from_user.username and from_user.username:
            updates["username"] = from_user.username
        if tg_user.display_name != new_name:
            updates["display_name"] = new_name
        if updates:
            TelegramUser.objects.filter(pk=tg_user.pk).update(**updates)
            for field, value in updates.items():
                setattr(tg_user, field, value)
    return tg_user, created


class BlockedUserMiddleware(BaseMiddleware):
    """Runs before every handler for messages and callback queries.

    - auto-creates a TelegramUser on first contact and injects it into handler
      kwargs as ``django_user``
    - if the user is blocked, answers with a single polite message and aborts
      the update without reaching any handler
    """

    async def __call__(self, handler, event, data):
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return await handler(event, data)

        tg_user, created = await sync_to_async(_get_or_create_telegram_user)(from_user)
        data["django_user"] = tg_user
        data["is_new_user"] = created

        if tg_user.is_blocked:
            await event.answer(t(tg_user.language, "blocked"))
            return None

        return await handler(event, data)
