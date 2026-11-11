"""Minimal Telegram Bot API client for the web app and the worker.

The aiogram service owns long polling; this module only needs the two
outbound methods the office side sends: ``sendMessage`` (a reporter
notification with an inline keyboard) and ``answerCallbackQuery``.
It deliberately uses plain ``urllib`` so Django workers do not need the
bot runtime as a dependency, and it NEVER raises into a request or a
worker cycle: a network failure is logged and returned as ``None``.

When ``settings.BOT_TOKEN`` is empty every function is a no-op, which
keeps local/offline runs and test suites safe.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger("bot_api")

API_BASE = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_SECONDS = 8


def is_enabled() -> bool:
    """True when a bot token is configured."""
    return bool(getattr(settings, "BOT_TOKEN", ""))


def _call(method: str, payload: dict):
    """POST one Bot API method and return its ``result`` (or ``None``)."""
    token = getattr(settings, "BOT_TOKEN", "")
    if not token:
        return None
    request = urllib.request.Request(
        API_BASE.format(token=token, method=method),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        logger.warning("Telegram API %s failed", method, exc_info=True)
        return None
    if not body.get("ok"):
        logger.warning(
            "Telegram API %s rejected: %s", method, body.get("description")
        )
        return None
    return body.get("result")


def inline_keyboard(rows):
    """Build an ``InlineKeyboardMarkup`` from ``[[(label, callback), ...], ...]``."""
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": callback} for label, callback in row]
            for row in rows
        ]
    }


def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    """Send one HTML message; returns the Telegram ``Message`` or ``None``."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", payload)


def answer_callback_query(callback_query_id: str, text: str | None = None,
                          show_alert: bool = False):
    """Acknowledge an inline button press (required by Telegram)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    return _call("answerCallbackQuery", payload)
