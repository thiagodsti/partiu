"""
ITA Airways (AZ) flight extractor.

Two email types are supported:

1. Boarding-pass email (noreply@ita-airways.com, "Your boarding pass"):
   Plain text has:
     FCO\\n\\nLIN\\n\\n21:00 - 13 Apr 2025\\n\\nAZ2058\\n\\n22:10 - 13 Apr 2025
   followed by:
     Booking code\\n\\nKKEZ2E

2. Check-in reminder (checkin@enews.ita-airways.com, "It's check-in time!"):
   Plain text has:
     PNR: KKEZ2E  Flight: AZ2058  Date: 13 April 2025
     From: Rome FCO  To: Milan LIN  Departure: 21:00
   (no arrival time — skipped)

Both email types are handled; the boarding-pass type yields a complete record.
"""

import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _get_text,
    enrich_flights,
    extract_seat,
    make_flight_dict,
)

# Boarding-pass plain-text pattern:
#   FCO  (newlines)  LIN  (newlines)  HH:MM - D Mon YYYY  (newlines)  AZ9999
#   (newlines)  HH:MM - D Mon YYYY
_boarding_pass_re = re.compile(
    r"\b(?P<dep>[A-Z]{3})\b"
    r"[\s\S]{0,60}?"
    r"\b(?P<arr>[A-Z]{3})\b"
    r"[\s\S]{0,120}?"
    r"(?P<dep_time>\d{1,2}:\d{2})\s*-\s*(?P<dep_date>\d{1,2}\s+\w+\s+\d{4})"
    r"[\s\S]{0,60}?"
    r"\b(?P<fn>AZ\s*\d{3,5})\b"
    r"[\s\S]{0,60}?"
    r"(?P<arr_time>\d{1,2}:\d{2})\s*-\s*(?P<arr_date>\d{1,2}\s+\w+\s+\d{4})",
)

# Seat extraction: "Zone / Seat\n...\n5 /5C"
_seat_re = re.compile(r"Zone\s*/\s*Seat[\s\S]{0,80}?(?:\d+\s*/\s*(\w+))", re.IGNORECASE)


def _extract_plain(body: str, rule) -> list[dict]:
    """Try to extract from the boarding-pass plain-text format."""
    m = _boarding_pass_re.search(body)
    if not m:
        return []

    dep_date = parse_flight_date(m.group("dep_date"))
    arr_date = parse_flight_date(m.group("arr_date"))
    if not dep_date or not arr_date:
        return []

    flight = make_flight_dict(
        rule,
        m.group("fn").replace(" ", ""),
        m.group("dep"),
        m.group("arr"),
        _build_datetime(dep_date, m.group("dep_time")),
        _build_datetime(arr_date, m.group("arr_time")),
    )
    if not flight:
        return []

    # ITA seat format: "Zone / Seat\n...\n5 /5C" — specific to this airline
    seat_m = _seat_re.search(body[body.find(m.group("fn")) :] if m.group("fn") in body else body)
    seat = seat_m.group(1).strip() if seat_m else extract_seat(body)
    if seat:
        flight["seat"] = seat

    return [flight]


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from an ITA Airways email."""
    body = email_msg.body or ""

    # The plain text is well-structured for the boarding-pass email
    flights = _extract_plain(body, rule)
    if flights:
        return enrich_flights(flights, body, email_msg.subject)

    # Try extracting text from the HTML body
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _extract_plain(html_text, rule)
        if flights:
            return enrich_flights(flights, html_text, email_msg.subject)

    return []
