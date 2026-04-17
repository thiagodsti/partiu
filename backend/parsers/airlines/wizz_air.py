"""
Wizz Air flight extractor.

Parses "Your travel itinerary" HTML confirmation emails from Wizz Air
(direct and Gmail-forwarded).

Plain-text structure produced by BS4 (one table cell per line):

  Flight confirmation code: GW8PSD
  ...
  GOING OUT
  Flight Number: W9 5362
  Departs from:
  Arrives to:
  Barcelona El Prat - Terminal 2 (BCN)
  London Luton (LTN)
  14/05/2026 09:35
  14/05/2026 11:00

Return legs appear after a "RETURN" / "GOING BACK" header with the same layout.
"""

import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from ..shared import (
    _extract_booking_ref_text,
    _extract_passenger_text,
    fix_overnight,
    normalize_fn,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# "Flight Number: W9 5362"  (may contain non-breaking space inside number)
_FLIGHT_NUM_RE = re.compile(
    r"Flight\s+Number:\s*([A-Z0-9]{1,3}[\s\xa0]\d{3,5}|\d{3,5})",
    re.IGNORECASE,
)

# "Barcelona El Prat - Terminal 2 (BCN)"  →  group 1 = BCN
_IATA_PAREN_RE = re.compile(r"\(([A-Z]{3})\)")

# "14/05/2026 09:35"  (non-breaking space tolerated between date and time)
_DATETIME_RE = re.compile(r"(\d{2}/\d{2}/\d{4})[\s\xa0]+(\d{2}:\d{2})")

# Leg section delimiters
_LEG_HEADER_RE = re.compile(r"^\s*(GOING\s+OUT|RETURN|GOING\s+BACK)\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_text(email_msg) -> str:
    """Extract clean text from HTML body, falling back to plain text."""
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        return soup.get_text(separator="\n", strip=True)
    return email_msg.body or ""


def _parse_wizz_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse 'DD/MM/YYYY' + 'HH:MM' into a UTC-aware datetime."""
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
        return dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _split_legs(lines: list[str]) -> list[list[str]]:
    """
    Split text lines into per-leg sections.

    Returns a list where each item is the lines belonging to one leg.
    Lines before the first leg header are kept as a preamble in leg 0.
    """
    legs: list[list[str]] = [[]]
    for line in lines:
        if _LEG_HEADER_RE.match(line):
            legs.append([line])
        else:
            legs[-1].append(line)
    return legs


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


def _extract_from_section(leg_text: str, booking_ref: str, rule) -> list[dict]:
    """Extract all flights from a single section of text."""
    fn_matches = [normalize_fn(m.group(1)) for m in _FLIGHT_NUM_RE.finditer(leg_text)]
    iata_matches = _IATA_PAREN_RE.findall(leg_text)
    dt_matches = _DATETIME_RE.findall(leg_text)

    # Each flight needs: 1 flight number, 2 IATA codes, 2 datetimes
    n_flights = min(len(fn_matches), len(iata_matches) // 2, len(dt_matches) // 2)
    if n_flights == 0:
        return []

    flights = []
    for i in range(n_flights):
        dep_iata = iata_matches[i * 2]
        arr_iata = iata_matches[i * 2 + 1]
        dep_dt = _parse_wizz_datetime(*dt_matches[i * 2])
        arr_dt = _parse_wizz_datetime(*dt_matches[i * 2 + 1])
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flights.append(
            {
                "airline_name": rule.airline_name,
                "airline_code": rule.airline_code,
                "flight_number": fn_matches[i],
                "departure_airport": dep_iata,
                "arrival_airport": arr_iata,
                "departure_datetime": dep_dt,
                "arrival_datetime": arr_dt,
                "booking_reference": booking_ref,
                "passenger_name": "",
                "seat": "",
                "cabin_class": "",
            }
        )
    return flights


def extract(email_msg, rule) -> list[dict]:
    text = _get_text(email_msg)
    lines = text.splitlines()

    booking_ref = _extract_booking_ref_text((email_msg.subject or "") + "\n" + text)
    passenger = _extract_passenger_text(text)

    leg_groups = _split_legs(lines)

    # If only one group (no section headers matched — e.g. non-English email),
    # treat the whole text as one block and extract all flights by position.
    # Otherwise each group is a header-delimited leg with exactly one flight.
    if len(leg_groups) == 1:
        flights = _extract_from_section("\n".join(leg_groups[0]), booking_ref, rule)
        if passenger:
            for f in flights:
                f.setdefault("passenger_name", passenger)
        return flights

    flights: list[dict] = []
    for leg_lines in leg_groups:
        leg_text = "\n".join(leg_lines)
        # Each header-delimited section has one flight; take first match only
        fn_m = _FLIGHT_NUM_RE.search(leg_text)
        if not fn_m:
            continue
        iata_matches = _IATA_PAREN_RE.findall(leg_text)
        if len(iata_matches) < 2:
            logger.debug("Wizz Air: fewer than 2 IATA codes in leg, skipping")
            continue
        dt_matches = _DATETIME_RE.findall(leg_text)
        if len(dt_matches) < 2:
            logger.debug("Wizz Air: fewer than 2 datetimes in leg, skipping")
            continue
        dep_dt = _parse_wizz_datetime(*dt_matches[0])
        arr_dt = _parse_wizz_datetime(*dt_matches[1])
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flights.append(
            {
                "airline_name": rule.airline_name,
                "airline_code": rule.airline_code,
                "flight_number": normalize_fn(fn_m.group(1)),
                "departure_airport": iata_matches[0],
                "arrival_airport": iata_matches[1],
                "departure_datetime": dep_dt,
                "arrival_datetime": arr_dt,
                "booking_reference": booking_ref,
                "passenger_name": passenger,
                "seat": "",
                "cabin_class": "",
            }
        )

    return flights
