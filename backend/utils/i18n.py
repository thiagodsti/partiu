"""
Minimal backend i18n — reuses the same JSON locale files as the frontend.

Usage:
    from .utils.i18n import t
    t("notif.checkin_title", locale="pt-BR", flight="LA8094")
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent.parent
_SUPPORTED = {"en", "pt-BR"}
_cache: dict[str, dict] = {}


def _candidate_dirs() -> list[Path]:
    """Places a locale JSON may live, most specific first.

    The repo checkout keeps them under the frontend source, but a deployed
    image may ship only the built frontend — see `backend/locales/`, which the
    Dockerfile populates from the same files.
    """
    dirs = []
    env_dir = os.getenv("LOCALES_DIR")
    if env_dir:
        dirs.append(Path(env_dir))
    dirs.append(_ROOT / "frontend" / "src" / "locales")
    dirs.append(_ROOT / "backend" / "locales")
    return dirs


def _strings(locale: str) -> dict:
    if locale not in _cache:
        for directory in _candidate_dirs():
            path = directory / f"{locale}.json"
            if not path.is_file():
                continue
            try:
                _cache[locale] = json.loads(path.read_text(encoding="utf-8"))
                break
            except Exception as exc:
                logger.warning("Could not load locale %s from %s: %s", locale, path, exc)
        else:
            # Returning the key itself is nearly invisible in a push notification,
            # so say plainly where we looked instead of failing quietly.
            logger.error(
                "No locale file for %s in any of: %s — translations will fall back to raw keys",
                locale,
                ", ".join(str(d) for d in _candidate_dirs()),
            )
            return {}
    return _cache[locale]


def t(key: str, locale: str = "en", **values: object) -> str:
    """Return the translated string for key in locale, falling back to English."""
    locale = locale if locale in _SUPPORTED else "en"
    value = _strings(locale).get(key)
    if value is None:
        value = _strings("en").get(key)
    template = value if value is not None else key
    if values:
        try:
            # svelte-i18n uses {name} placeholders — same as str.format_map
            return template.format(**values)
        except (KeyError, ValueError):
            return template
    return template
