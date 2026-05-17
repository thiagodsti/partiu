"""
Minimal backend i18n — reuses the same JSON locale files as the frontend.

Usage:
    from .i18n import t
    t("notif.checkin_title", locale="pt-BR", flight="LA8094")
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCALES_DIR = Path(__file__).parent.parent / "frontend" / "src" / "locales"
_SUPPORTED = {"en", "pt-BR"}
_cache: dict[str, dict] = {}


def _strings(locale: str) -> dict:
    if locale not in _cache:
        path = _LOCALES_DIR / f"{locale}.json"
        try:
            _cache[locale] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load locale %s: %s", locale, exc)
            _cache[locale] = {}
    return _cache[locale]


def t(key: str, locale: str = "en", **values: object) -> str:
    """Return the translated string for key in locale, falling back to English."""
    locale = locale if locale in _SUPPORTED else "en"
    template = _strings(locale).get(key) or _strings("en").get(key) or key
    if values:
        try:
            # svelte-i18n uses {name} placeholders — same as str.format_map
            return template.format(**values)
        except (KeyError, ValueError):
            return template
    return template
