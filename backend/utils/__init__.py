"""
Generic, dependency-light helper package used across every feature — nothing
here is tied to one feature, and nothing here touches the database (compare
airports/timezone.py, which does and therefore lives outside this package).

  dates.py - flight-number validation, ISO datetime conversion, duration/status calc
  text.py  - accent folding for airport name matching
  i18n.py  - minimal backend translations, reusing the frontend's locale JSON files

Re-exports dates.py and text.py here so ``from ..utils import now_iso`` etc. keep working
unchanged across the ~20 modules that import them (same reasoning as
backend/auth/__init__.py). i18n.py's ``t()`` is imported explicitly as
``from ..utils.i18n import t`` at its few call sites instead, since bundling
translation lookups into this same flat namespace would be more confusing
than helpful.
"""

from .dates import (
    FLIGHT_NUMBER_RE,
    calc_duration_minutes,
    calc_flight_status,
    dt_to_iso,
    now_iso,
    validate_flight_number,
)
from .text import fold_text

__all__ = [
    "FLIGHT_NUMBER_RE",
    "calc_duration_minutes",
    "calc_flight_status",
    "dt_to_iso",
    "fold_text",
    "now_iso",
    "validate_flight_number",
]
