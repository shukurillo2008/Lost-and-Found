"""Automatic translation helpers for reference data.

Staff types a value in any one language (uz, en or ru); the remaining blank
translation columns are filled automatically via an online translator when
available. If the service is disabled or unreachable the fields are left
blank and staff can fill them in manually.
"""
from contextlib import AbstractContextManager, contextmanager

PROVIDER_LANGS = {"uz": "uzbek", "en": "english", "ru": "russian"}

_DISABLE_DEPTH = 0


def _auto_translate_enabled() -> bool:
    from django.conf import settings

    return getattr(settings, "AUTO_TRANSLATE", False) and _DISABLE_DEPTH == 0


def disabled() -> "AbstractContextManager":
    """Context manager: skip automatic translation inside the block
    (bulk seeding / migrations heavy paths)."""
    global _DISABLE_DEPTH

    @contextmanager
    def _ctx():
        global _DISABLE_DEPTH
        _DISABLE_DEPTH += 1
        try:
            yield
        finally:
            _DISABLE_DEPTH -= 1

    return _ctx()


def _clean(text: str) -> str:
    # MyMemory sometimes returns extra lines / whitespace; keep the first line.
    first_line = (text or "").strip().splitlines()
    return first_line[0].strip() if first_line else ""


def translate(text: str, target_lang: str, source_lang: str = "uz") -> str:
    """Translate ``text`` to ``target_lang`` (uz/en/ru). "" on any failure."""
    text = (text or "").strip()
    if not text or not _auto_translate_enabled():
        return ""
    try:
        from django.conf import settings

        from deep_translator import MyMemoryTranslator

        # A contact email raises the MyMemory free quota to 50,000 chars/day.
        email = (getattr(settings, "MYMEMORY_EMAIL", "") or "").strip()
        translator = MyMemoryTranslator(
            source=PROVIDER_LANGS[source_lang.lower()],
            target=PROVIDER_LANGS[target_lang.lower()],
            **({"email": email} if email else {}),
        )
        return _clean(translator.translate(text))
    except Exception:
        return ""


def auto_fill(fields_map: dict[str, str], source_lang: str | None = None) -> None:
    """Fill blank target fields by translating the first non-empty source.

    ``fields_map`` maps language code -> current value, e.g.
    ``{"uz": "Kutubxona", "en": "", "ru": ""}``. Values are updated in place.
    ``source_lang`` forces the source field (falls back to first non-empty).
    """
    if source_lang is None:
        source_lang = next(
            (lang for lang, value in fields_map.items() if (value or "").strip()), None
        )
        if source_lang is None:
            return
    source_text = (fields_map[source_lang] or "").strip()
    if not source_text:
        return
    for lang, value in fields_map.items():
        if lang == source_lang or (value or "").strip():
            continue
        translated = translate(source_text, lang, source_lang)
        if translated:
            fields_map[lang] = translated


def apply_to_fields(obj, base_fields) -> None:
    """Auto-fill translation columns on ``obj`` for each given base prefix."""
    for base in base_fields:
        fields_map = {
            lang: getattr(obj, f"{base}_{lang}", "") or ""
            for lang in ("uz", "en", "ru")
        }
        before = dict(fields_map)
        auto_fill(fields_map)
        for lang, value in fields_map.items():
            if value != before[lang]:
                setattr(obj, f"{base}_{lang}", value)
