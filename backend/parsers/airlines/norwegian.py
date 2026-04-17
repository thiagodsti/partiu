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

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    make_flight_dict,
    resolve_iata,
)
from .sas import extract as _sas_extract
from .sas import extract_bs4 as _sas_extract_bs4
from .sas import extract_regex as _sas_extract_regex

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# "Travel documents" format extractor
# ---------------------------------------------------------------------------

_travel_docs_marker_re = re.compile(r"YOUR BOOKING REFERENCE IS", re.IGNORECASE)

# Per-flight block pattern (applied to whitespace-collapsed text):
#   DY4371\n-\n14 Aug 2019\n17:10\nStockholm-Arlanda\n20:45\nSicily-Catania\n
_flight_block_re = re.compile(
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
    """Normalise the plain-text body: collapse consecutive blank lines to one."""
    lines = [line.rstrip() for line in body.splitlines()]
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
    """Extract flights from the Norwegian "Travel documents" booking confirmation."""
    body = email_msg.body
    if not _travel_docs_marker_re.search(body):
        return []

    collapsed = _collapse_body(body)

    flights = []
    for m in _flight_block_re.finditer(collapsed):
        dep_date = parse_flight_date(m.group(2).strip())
        if not dep_date:
            continue

        dep_airport = resolve_iata(m.group(4).strip())
        arr_airport = resolve_iata(m.group(6).strip())
        if not dep_airport or not arr_airport:
            logger.debug(
                "norwegian: could not resolve airports for %r / %r",
                m.group(4).strip(),
                m.group(6).strip(),
            )
            continue

        dep_dt = _build_datetime(dep_date, m.group(3).strip())
        arr_dt = _build_datetime(dep_date, m.group(5).strip())
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)

        flight = make_flight_dict(
            rule,
            m.group(1).strip(),
            dep_airport,
            arr_airport,
            dep_dt,
            arr_dt,
        )
        if flight:
            flights.append(flight)

    return enrich_flights(flights, collapsed, email_msg.subject)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """
    Unified entry point for Norwegian Air Shuttle emails.

    Tries the "Travel documents" format first; falls back to the
    SAS-compatible extractor for the older Norwegian email style.
    """
    flights = _extract_travel_documents(email_msg, rule)
    if flights:
        return flights

    return _sas_extract(email_msg, rule)


# Re-export SAS helpers so any code importing these names from this module
# still works (e.g. the engine's generic BS4/regex dispatch).
extract_bs4 = _sas_extract_bs4
extract_regex = _sas_extract_regex
