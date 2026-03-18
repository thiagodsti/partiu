"""
Compatibility shim — BS4 extractors have moved to parsers/airlines/.
This module re-exports extract_with_bs4 so any existing imports keep working.
"""

from .airlines import extract_with_bs4  # noqa: F401
from .engine import parse_flight_date, MONTH_MAP  # noqa: F401
