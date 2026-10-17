"""All user-facing bot strings in three languages.

Handlers and keyboards must take every piece of visible text from here —
bare strings in handler code are not allowed.
"""

SUPPORTED_LANGUAGES = ("uz", "ru", "en")
DEFAULT_LANGUAGE = "uz"

STRINGS = {
    "uz": {
        "choose_language": "🌐 Tilni tanlang:",
        "language_changed": "✅ Til o‘zgartirildi.",
        "main_menu_title": "👋 Assalomu alaykum, {name}!\n\nQuyidagi menyudan foydalaning:",
        "hint_settings": "ℹ️ Tilni istalgan vaqtda /settings buyrug‘i bilan almashtirishingiz mumkin.",
        "settings_title": "⚙️ Sozlamalar — interfeys tilini tanlang:",
        "menu_lost": "🧳 Yo‘qotdim",
        "menu_found": "🎁 Topdim",
        "menu_recent": "🗂 Oxirgi topilmalar",
        "menu_my_reports": "📄 Mening arizalarim",
        "blocked": "🚫 Siz uchun bu botdan foydalanish vaqtincha cheklangan. Iltimos, institut ofisiga murojaat qiling.",
        "wip_menu": "🚧 Bu bo‘lim tayyorlanmoqda va keyingi bosqichda ochiladi.",
        "fallback": "🤔 Bunday buyruq mavjud emas.\n\nQuyidagi menyudan foydalaning:",
        "lang_uz": "🇺🇿 O‘zbekcha",
        "lang_ru": "🇷🇺 Русский",
        "lang_en": "🇬🇧 English",
    },
    "ru": {
        "choose_language": "🌐 Пожалуйста, выберите язык:",
        "language_changed": "✅ Язык изменён.",
        "main_menu_title": "👋 Здравствуйте, {name}!\n\nПожалуйста, воспользуйтесь меню ниже:",
        "hint_settings": "ℹ️ Управляйте языком в любой момент с помощью команды /settings.",
        "settings_title": "⚙️ Настройки — выберите язык интерфейса:",
        "menu_lost": "🧳 Потерял(а)",
        "menu_found": "🎁 Нашёл(а)",
        "menu_recent": "🗂 Последние находки",
        "menu_my_reports": "📄 Мои заявки",
        "blocked": "🚫 Доступ к боту для вас временно закрыт. Пожалуйста, свяжитесь с офисом кампуса.",
        "wip_menu": "🚧 Этот раздел ещё в разработке и появится в следующей части.",
        "fallback": "🤔 Такой команды нет.\n\nПожалуйста, пользуйтесь меню ниже:",
        "lang_uz": "🇺🇿 O‘zbekcha",
        "lang_ru": "🇷🇺 Русский",
        "lang_en": "🇬🇧 English",
    },
    "en": {
        "choose_language": "🌐 Please choose your language:",
        "language_changed": "✅ Language switched.",
        "main_menu_title": "👋 Hello, {name}!\n\nPlease use the menu below:",
        "hint_settings": "ℹ️ Switch the language at any time via the /settings command.",
        "settings_title": "⚙️ Settings — choose the interface language:",
        "menu_lost": "🧳 I lost something",
        "menu_found": "🎁 I found something",
        "menu_recent": "🗂 Recent found items",
        "menu_my_reports": "📄 My reports",
        "blocked": "🚫 Your access to this bot is temporarily restricted. Please contact the campus office.",
        "wip_menu": "🚧 This section is still being prepared and opens in the next stage.",
        "fallback": "🤔 There is no such command.\n\nPlease use the menu below:",
        "lang_uz": "🇺🇿 O‘zbekcha",
        "lang_ru": "🇷🇺 Русский",
        "lang_en": "🇬🇧 English",
    },
}


def t(lang: str, key: str) -> str:
    """Translate: fall back to the default language, then to the key itself."""
    if lang in STRINGS and key in STRINGS[lang]:
        return STRINGS[lang][key]
    if key in STRINGS[DEFAULT_LANGUAGE]:
        return STRINGS[DEFAULT_LANGUAGE][key]
    return key
