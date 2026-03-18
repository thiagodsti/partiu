"""
Per-airline BS4 extraction dispatch.

Each airline module exposes an extract_bs4(html, rule, email_msg) -> list[dict]
function. extract_with_bs4() below routes to the right one based on the rule's
custom_extractor field.
"""

import logging

from .azul import extract_bs4 as _azul
from .kiwi import extract_bs4 as _kiwi
from .latam import extract_bs4 as _latam
from .lufthansa import extract_bs4 as _lufthansa
from .norwegian import extract_bs4 as _norwegian
from .sas import extract_bs4 as _sas

logger = logging.getLogger(__name__)

_EXTRACTORS = {
    "latam": _latam,
    "sas": _sas,
    "norwegian": _norwegian,
    "lufthansa": _lufthansa,
    "azul": _azul,
    "kiwi": _kiwi,
}


def extract_with_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Try BS4 extraction for the matched airline rule.
    Returns [] if no extractor is registered or extraction fails,
    signalling the caller to fall back to regex.
    """
    if not html or not html.strip():
        return []

    extractor_name = getattr(rule, "custom_extractor", "")
    extractor = _EXTRACTORS.get(extractor_name)
    if not extractor:
        return []

    try:
        result = extractor(html, rule, email_msg)
        if result:
            logger.debug(
                "BS4 extractor '%s' found %d flight(s)", extractor_name, len(result)
            )
        return result
    except Exception:
        logger.debug(
            "BS4 extractor '%s' failed, falling back to regex",
            extractor_name,
            exc_info=True,
        )
        return []
