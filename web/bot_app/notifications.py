"""Reporter notifications sent from the office side to Telegram.

Two events reach the reporter:

* a **match suggestion** — "is this your item?" with Yes/No inline
  buttons; the answer comes back to ``bot/notify.py`` and is applied
  through the shared ``matching.services.apply_decision``;
* a **handover** — the item was returned, a plain informational message;
* an **expired report** — closed after 90 days with a one-tap reopen
  button handled by ``bot/notify.py``.

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
from reports.models import LostReport

from . import telegram_api

logger = logging.getLogger("bot_notify")

CONFIRM_PREFIX = "match-yes:"
REJECT_PREFIX = "match-no:"
REOPEN_PREFIX = "reopen:"

OUTCOME_ALREADY = "already"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_NOT_YOURS = "not_yours"
OUTCOME_REOPENED = "reopened"

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
        "match_confirmed": (
            "✅ <b>Moslik tasdiqlandi!</b>\n\n"
            "«{title}» arizangiz bo‘yicha buyum topildi:\n"
            "📦 <b>{item}</b>\n\n"
            "{contact}\n\n"
            "Buyumni olish uchun ofisga shaxsni tasdiqlovchi hujjat bilan keling."
        ),
        "contact_finder": "👤 Topgan odam: {name}",
        "contact_username": "💬 Telegram: @{username}",
        "contact_phone": "📞 Telefon: {phone}",
        "contact_office": "👤 Topgan odamning kontakt ma’lumotlarini ofis xodimlari taqdim etadi.",
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
        "expired": (
            "⏳ <b>Ariza yopildi</b>\n\n"
            "«{title}» bo‘yicha arizangiz 90 kundan oshgani uchun avtomatik yopildi.\n\n"
            "Agar hali ham qidirayotgan bo‘lsangiz, quyidagi tugma bilan qayta oching."
        ),
        "reopen_btn": "🔄 Qayta ochish",
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
        "match_confirmed": (
            "✅ <b>Совпадение подтверждено!</b>\n\n"
            "По вашей заявке «{title}» найдена вещь:\n"
            "📦 <b>{item}</b>\n\n"
            "{contact}\n\n"
            "Для получения вещи придите в офис с документом, удостоверяющим личность."
        ),
        "contact_finder": "👤 Нашедший: {name}",
        "contact_username": "💬 Telegram: @{username}",
        "contact_phone": "📞 Телефон: {phone}",
        "contact_office": "👤 Контактные данные нашедшего предоставят сотрудники офиса.",
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
        "expired": (
            "⏳ <b>Заявка закрыта</b>\n\n"
            "Ваша заявка «{title}» автоматически закрыта, так как прошло более 90 дней.\n\n"
            "Если вы всё ещё ищете вещь, откройте заявку кнопкой ниже."
        ),
        "reopen_btn": "🔄 Открыть заново",
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
        "match_confirmed": (
            "✅ <b>Match confirmed!</b>\n\n"
            "An item matching your report “{title}” has been found:\n"
            "📦 <b>{item}</b>\n\n"
            "{contact}\n\n"
            "Bring an ID document to the office to collect the item."
        ),
        "contact_finder": "👤 Found by: {name}",
        "contact_username": "💬 Telegram: @{username}",
        "contact_phone": "📞 Phone: {phone}",
        "contact_office": "👤 The office staff will provide the finder's contact details.",
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
        "expired": (
            "⏳ <b>Report closed</b>\n\n"
            "Your report “{title}” was closed automatically because it is older than 90 days.\n\n"
            "If you are still looking for the item, reopen it with the button below."
        ),
        "reopen_btn": "🔄 Reopen report",
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


def _finder_report(suggestion: MatchSuggestion):
    """The found report behind a suggestion, or ``None`` for walk-ins."""
    item = suggestion.stored_item
    if item is not None and item.found_report_id:
        return item.found_report
    return suggestion.found_report


def _finder_contact_block(report, lang: str) -> str:
    """Contact lines for the finder, gated by the opt-in consent flag.

    ``FoundReport.finder_contact_allowed`` is the finder's decision; when
    it is off (or the finder never used the bot) the office mediates and
    no personal contact is revealed.
    """
    if report is None or not report.finder_contact_allowed:
        return text_for(lang, "contact_office")
    finder = report.reporter
    if finder is None:
        return text_for(lang, "contact_office")
    lines = [
        text_for(lang, "contact_finder", name=escape(finder.display_name))
    ]
    if finder.username:
        lines.append(text_for(lang, "contact_username", username=escape(finder.username)))
    if getattr(finder, "phone", None):
        lines.append(text_for(lang, "contact_phone", phone=escape(finder.phone)))
    if len(lines) == 1:
        # Name alone is not a contact channel; let the office mediate.
        return text_for(lang, "contact_office")
    return "\n".join(lines)


def match_confirmed_text(suggestion: MatchSuggestion, lang: str | None = None) -> str:
    """Localized "match confirmed" message with the finder's contact."""
    reporter = suggestion.lost_report.reporter
    lang = lang or _reporter_language(reporter)
    item_label, _category, _date = _suggestion_item(suggestion, lang)
    return text_for(
        lang,
        "match_confirmed",
        title=escape(suggestion.lost_report.title_in(lang)),
        item=escape(item_label),
        contact=_finder_contact_block(_finder_report(suggestion), lang),
    )


def match_confirmed_text_for(suggestion_id: int, lang: str) -> str | None:
    """Fetch a suggestion and build the confirmation text (bot path)."""
    suggestion = (
        MatchSuggestion.objects.select_related(
            "lost_report__reporter",
            "stored_item__found_report__reporter",
            "found_report__reporter",
        )
        .filter(pk=suggestion_id)
        .first()
    )
    if suggestion is None:
        return None
    return match_confirmed_text(suggestion, lang)


def notify_match_confirmed(suggestion: MatchSuggestion) -> bool:
    """Tell the lost reporter that staff confirmed the match, with the
    finder's contact (opt-in) so they can arrange the pick-up."""
    reporter = suggestion.lost_report.reporter
    if not telegram_api.is_enabled() or not _can_reach(reporter):
        return False
    body = match_confirmed_text(suggestion, _reporter_language(reporter))
    sent = telegram_api.send_message(reporter.telegram_id, body)
    if sent:
        logger.info(
            "notified reporter %s about confirmed match #%s",
            reporter.telegram_id, suggestion.pk,
        )
    return bool(sent)


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


def notify_expired(report: LostReport) -> bool:
    """Tell the reporter that a 90-day-old report was closed + reopen button."""
    reporter = report.reporter
    if not telegram_api.is_enabled() or not _can_reach(reporter):
        return False
    lang = _reporter_language(reporter)
    body = text_for(lang, "expired", title=escape(report.title_in(lang)))
    keyboard = telegram_api.inline_keyboard([
        [(text_for(lang, "reopen_btn"), f"{REOPEN_PREFIX}{report.pk}")]
    ])
    sent = telegram_api.send_message(reporter.telegram_id, body, keyboard)
    if sent:
        logger.info("notified reporter %s about expired report #%s",
                    reporter.telegram_id, report.pk)
    return bool(sent)


def reopen_from_bot(telegram_user, report_id: int) -> str:
    """Reopen an auto-expired report from the bot's one-tap button.

    Returns ``reopened`` on success, ``already`` when the report is no
    longer expired (already reopened / matched / returned), ``not_found``
    for a deleted row and ``not_yours`` for another Telegram account.
    """
    report = LostReport.objects.filter(pk=report_id).only(
        "pk", "status", "reporter_id"
    ).first()
    if report is None:
        return OUTCOME_NOT_FOUND
    if report.reporter_id != telegram_user.pk:
        return OUTCOME_NOT_YOURS
    if report.status != "expired":
        return OUTCOME_ALREADY
    # Queryset update is race-safe and skips the auto-translate save hook;
    # reopened_at restarts the 90-day expiry clock.
    updated = LostReport.objects.filter(pk=report.pk, status="expired").update(
        status="open", reopened_at=timezone.now()
    )
    return OUTCOME_REOPENED if updated else OUTCOME_ALREADY
