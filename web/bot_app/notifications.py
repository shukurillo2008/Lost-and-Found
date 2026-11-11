"""Reporter notifications sent from the office side to Telegram.

Two events reach the reporter:

* a **match suggestion** — "is this your item?" with Yes/No inline
  buttons; the answer comes back to ``bot/notify.py`` and is applied
  through the shared ``matching.services.apply_decision``;
* a **handover** — the item was returned, a plain informational message.

Every function is a safe no-op when the bot token is missing, the
reporter never used the bot (no ``telegram_id``) or is blocked.
"""
import logging
from html import escape

from django.utils import timezone

from matching.models import MatchSuggestion
from matching.services import (
    OUTCOME_CONFIRMED,
    OUTCOME_NOOP,
    OUTCOME_REJECTED,
    apply_decision,
)

from . import telegram_api

logger = logging.getLogger("bot_notify")

CONFIRM_PREFIX = "match-yes:"
REJECT_PREFIX = "match-no:"

OUTCOME_ALREADY = "already"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_NOT_YOURS = "not_yours"

TEXTS = {
    "uz": {
        "suggestion": (
            "🔎 <b>Mumkin bo‘lgan topilma!</b>\n\n"
            "«{title}» arizangizga o‘xshash buyum omborga qabul qilindi:\n\n"
            "📦 <b>{item}</b>\n🏷 {category}\n📅 {date}\n\n"
            "Bu sizning buyumingizmi?"
        ),
        "yes": "✅ Ha, bu meniki",
        "no": "❌ Yo‘q, bu meniki emas",
        "confirmed": (
            "✅ Rahmat! Arizangiz «mos kelgan» deb belgilandi. "
            "Buyumni olish uchun ofisga shaxsni tasdiqlovchi hujjat bilan keling."
        ),
        "rejected": (
            "❌ Tushunarli. Boshqa mos buyum topilsa, yana xabar beramiz."
        ),
        "handover": (
            "🎉 <b>Buyumingiz qaytarildi!</b>\n\n"
            "«{title}» bo‘yicha buyum ofisdan topshirildi ({date}).\n"
            "Savollaringiz bo‘lsa, institut ofisiga murojaat qiling."
        ),
    },
    "ru": {
        "suggestion": (
            "🔎 <b>Возможная находка!</b>\n\n"
            "В офис поступила вещь, похожая на вашу заявку «{title}»:\n\n"
            "📦 <b>{item}</b>\n🏷 {category}\n📅 {date}\n\n"
            "Это ваша вещь?"
        ),
        "yes": "✅ Да, это моя вещь",
        "no": "❌ Нет, это не моя вещь",
        "confirmed": (
            "✅ Спасибо! Заявка отмечена как «совпадение». "
            "Для получения вещи придите в офис с документом, удостоверяющим личность."
        ),
        "rejected": (
            "❌ Понятно. Если найдётся другая подходящая вещь, мы сообщим."
        ),
        "handover": (
            "🎉 <b>Ваша вещь возвращена!</b>\n\n"
            "Вещь по заявке «{title}» выдана из офиса ({date}).\n"
            "По вопросам обращайтесь в офис кампуса."
        ),
    },
    "en": {
        "suggestion": (
            "🔎 <b>A possible match!</b>\n\n"
            "An item similar to your report “{title}” arrived at the office:\n\n"
            "📦 <b>{item}</b>\n🏷 {category}\n📅 {date}\n\n"
            "Is this yours?"
        ),
        "yes": "✅ Yes, it is mine",
        "no": "❌ No, it is not mine",
        "confirmed": (
            "✅ Thank you! Your report is marked as matched. "
            "Bring an ID document to the office to collect the item."
        ),
        "rejected": (
            "❌ Understood. We will let you know if another suitable item appears."
        ),
        "handover": (
            "🎉 <b>Your item has been returned!</b>\n\n"
            "The item for report “{title}” was handed over at the office ({date}).\n"
            "Contact the campus office if you have any questions."
        ),
    },
}

DEFAULT_LANGUAGE = "uz"


def text_for(lang: str, key: str, **values) -> str:
    """Localized notification text (falls back to Uzbek, then the key)."""
    block = TEXTS.get(lang) or TEXTS[DEFAULT_LANGUAGE]
    template = block.get(key) or TEXTS[DEFAULT_LANGUAGE].get(key) or key
    return template.format(**values)


def _reporter_language(reporter) -> str:
    lang = getattr(reporter, "language", DEFAULT_LANGUAGE)
    return lang if lang in TEXTS else DEFAULT_LANGUAGE


def _can_reach(reporter) -> bool:
    return bool(reporter and reporter.telegram_id and not reporter.is_blocked)


def _suggestion_item(suggestion, lang: str) -> tuple:
    """(item label, category label, date label) for the outbound message."""
    item = suggestion.stored_item
    if item is not None:
        return (
            f"{item.shelf_code} — {item.title}",
            item.category.localized_name(lang),
            timezone.localtime(item.received_at).strftime("%d.%m.%Y"),
        )
    found = suggestion.found_report
    if found is not None:
        return (
            found.title_in(lang),
            found.category.localized_name(lang),
            found.date_found.strftime("%d.%m.%Y"),
        )
    return ("—", "—", "—")


def notify_suggestion(suggestion: MatchSuggestion) -> bool:
    """Ask the lost reporter whether a suggested item is theirs."""
    reporter = suggestion.lost_report.reporter
    if not telegram_api.is_enabled() or not _can_reach(reporter):
        return False
    lang = _reporter_language(reporter)
    item_label, category_label, date_label = _suggestion_item(suggestion, lang)
    body = text_for(
        lang,
        "suggestion",
        title=escape(suggestion.lost_report.title_in(lang)),
        item=escape(item_label),
        category=escape(category_label),
        date=escape(date_label),
    )
    keyboard = telegram_api.inline_keyboard([
        [
            (text_for(lang, "yes"), f"{CONFIRM_PREFIX}{suggestion.pk}"),
            (text_for(lang, "no"), f"{REJECT_PREFIX}{suggestion.pk}"),
        ]
    ])
    sent = telegram_api.send_message(reporter.telegram_id, body, keyboard)
    if sent:
        logger.info(
            "notified reporter %s about suggestion #%s", reporter.telegram_id, suggestion.pk
        )
    return bool(sent)


def notify_handover(handover) -> bool:
    """Tell the claimant that the item left the office."""
    report = handover.lost_report
    if report is None:
        return False
    reporter = report.reporter
    if not telegram_api.is_enabled() or not _can_reach(reporter):
        return False
    lang = _reporter_language(reporter)
    body = text_for(
        lang,
        "handover",
        title=escape(handover.stored_item.title),
        date=timezone.localtime(handover.handed_at).strftime("%d.%m.%Y"),
    )
    sent = telegram_api.send_message(reporter.telegram_id, body)
    if sent:
        logger.info("notified reporter %s about handover #%s",
                    reporter.telegram_id, handover.pk)
    return bool(sent)


def decide_from_bot(telegram_user, suggestion_id: int, action: str) -> str:
    """Apply a reporter's Yes/No answer coming from an inline button.

    Returns an ``OUTCOME_*`` string: confirmed/rejected on success,
    ``already`` for a repeated answer, ``not_found`` for a deleted row
    and ``not_yours`` when another Telegram account presses the buttons.
    """
    suggestion = (
        MatchSuggestion.objects.select_related("lost_report__reporter")
        .filter(pk=suggestion_id)
        .first()
    )
    if suggestion is None:
        return OUTCOME_NOT_FOUND
    if suggestion.lost_report.reporter_id != telegram_user.pk:
        return OUTCOME_NOT_YOURS
    outcome = apply_decision(suggestion, action, reviewer=None)
    if outcome == OUTCOME_NOOP:
        return OUTCOME_ALREADY
    if outcome == OUTCOME_CONFIRMED:
        return OUTCOME_CONFIRMED
    if outcome == OUTCOME_REJECTED:
        return OUTCOME_REJECTED
    return OUTCOME_ALREADY
