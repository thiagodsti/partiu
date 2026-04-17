"""
Norwegian Air Shuttle flight extractor.

Two formats are supported:
  1. "Travel documents" format — the newer Norwegian booking confirmation email
     that lists flights under "YOUR BOOKING REFERENCE IS:" / "Flight info".
  2. Legacy SAS-compatible format — re-uses the SAS extractor for the older
     Norwegian email style (same HTML/text structure as SAS).

Entry point: extract()
"""

import logging
import re
from datetime import datetime

from ..engine import parse_flight_date
from ..shared import (
    _extract_booking_ref_text,
    _extract_passenger_text,
    _make_aware,
    _make_flight_dict,
    fix_overnight,
    resolve_iata,
)
from .sas import extract as _sas_extract
from .sas import extract_bs4 as _sas_extract_bs4
from .sas import extract_regex as _sas_extract_regex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# "Travel documents" format extractor
# ---------------------------------------------------------------------------

# Detects the Norwegian "Travel documents" booking confirmation:
#   YOUR BOOKING REFERENCE IS:\n<REF>
_TRAVEL_DOCS_MARKER_RE = re.compile(
    r"YOUR BOOKING REFERENCE IS",
    re.IGNORECASE,
)

# Per-flight block pattern (applied to whitespace-collapsed text):
#   DY4371\n-\n14 Aug 2019\n17:10\nStockholm-Arlanda\n20:45\nSicily-Catania\n
_FLIGHT_BLOCK_RE = re.compile(
    r"(DY\d{4,5}|D8\d{4,5})\n"  # flight number
    r"-\n"  # separator
    r"(\d{1,2}\s+\w{3,}\s+\d{4})\n"  # date e.g. "14 Aug 2019"
    r"\n?"  # optional blank line
    r"(\d{2}:\d{2})\n"  # departure time
    r"([A-Za-z][A-Za-z -]+)\n"  # departure city/airport name
    r"\n?"  # optional blank line
    r"(\d{2}:\d{2})\n"  # arrival time
    r"([A-Za-z][A-Za-z -]+)\n",  # arrival city/airport name
    re.MULTILINE,
)


def _collapse_body(body: str) -> str:
    """
    Normalise the plain-text body: strip trailing whitespace from each line,
    collapse sequences of blank lines to a single newline, and ensure a
    trailing newline so the per-flight regex always has a terminating \\n.
    """
    lines = [line.rstrip() for line in body.splitlines()]
    # Collapse multiple consecutive blank lines to one
    collapsed: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank
    return "\n".join(collapsed) + "\n"


def _extract_travel_documents(email_msg, rule) -> list[dict]:
    """
    Extract flights from the Norwegian "Travel documents" booking confirmation.

    Returns an empty list when the email does not match this format.
    """
    body = email_msg.body
    if not _TRAVEL_DOCS_MARKER_RE.search(body):
        return []

    collapsed = _collapse_body(body)

    booking_ref = _extract_booking_ref_text((email_msg.subject or "") + "\n" + collapsed)
    passenger = _extract_passenger_text(body)

    flights = []
    for m in _FLIGHT_BLOCK_RE.finditer(collapsed):
        flight_number = m.group(1).strip()
        date_raw = m.group(2).strip()
        dep_time_str = m.group(3).strip()
        dep_city = m.group(4).strip()
        arr_time_str = m.group(5).strip()
        arr_city = m.group(6).strip()

        dep_date = parse_flight_date(date_raw)
        if not dep_date:
            logger.debug("norwegian: could not parse date %r", date_raw)
            continue

        dep_airport = resolve_iata(dep_city)
        arr_airport = resolve_iata(arr_city)
        if not dep_airport or not arr_airport:
            logger.debug("norwegian: could not resolve airports for %r / %r", dep_city, arr_city)
            continue

        dep_h, dep_m_val = map(int, dep_time_str.split(":"))
        arr_h, arr_m_val = map(int, arr_time_str.split(":"))

        dep_dt = _make_aware(
            datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m_val)
        )
        arr_raw = _make_aware(
            datetime(dep_date.year, dep_date.month, dep_date.day, arr_h, arr_m_val)
        )
        arr_dt = fix_overnight(dep_dt, arr_raw)

        flight = _make_flight_dict(
            rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref, passenger
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """
    Unified entry point for Norwegian Air Shuttle emails.

    Tries the "Travel documents" format first; falls back to the
    SAS-compatible extractor for the older Norwegian email style.
    """
    result = _extract_travel_documents(email_msg, rule)
    if result:
        return result

    return _sas_extract(email_msg, rule)


# Re-export SAS helpers so any code importing these names from this module
# still works (e.g. the engine's generic BS4/regex dispatch).
extract_bs4 = _sas_extract_bs4
extract_regex = _sas_extract_regex
