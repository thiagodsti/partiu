"""
ITA Airways (AZ) flight extractor.

Two email types are supported:

1. Boarding-pass email (noreply@ita-airways.com, "Your boarding pass"):
   Plain text has:
     FCO\n\nLIN\n\n21:00 - 13 Apr 2025\n\nAZ2058\n\n22:10 - 13 Apr 2025
   followed by:
     Booking code\n\nKKEZ2E

2. Check-in reminder (checkin@enews.ita-airways.com, "It's check-in time!"):
   Plain text has:
     PNR: KKEZ2E  Flight: AZ2058  Date: 13 April 2025
     From: Rome FCO  To: Milan LIN  Departure: 21:00
   (no arrival time — skipped)

Both email types are handled; the boarding-pass type yields a complete record.
"""

import logging
import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import _build_datetime, _get_text, _make_flight_dict

logger = logging.getLogger(__name__)

# Boarding-pass plain-text pattern:
#   FCO  (newlines)  LIN  (newlines)  HH:MM - D Mon YYYY  (newlines)  AZ9999
#   (newlines)  HH:MM - D Mon YYYY
_BOARDING_RE = re.compile(
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

# Booking reference — two formats:
#   "Booking code\n\nTerminal\n\nBoarding\n\nGate\n\nKKEZ2E" (boarding pass)
#   "PNR: KKEZ2E"  (check-in)
_PNR_RE = re.compile(
    r"(?:"
    r"Booking\s+code[\s\S]{0,60}?Gate\s+([A-Z0-9]{5,8})"  # boarding-pass table
    r"|"
    r"PNR[:\s]+([A-Z0-9]{5,8})"  # check-in plain format
    r")",
    re.IGNORECASE,
)

# Passenger name
_PASSENGER_RE = re.compile(
    r"(?:Dear|Passenger)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+){1,5})",
    re.IGNORECASE,
)

# Seat extraction: "Zone / Seat\n...\n5 /5C"
_SEAT_RE = re.compile(r"Zone\s*/\s*Seat[\s\S]{0,80}?(?:\d+\s*/\s*(\w+))", re.IGNORECASE)


def _extract_plain(body: str, rule) -> list[dict]:
    m = _BOARDING_RE.search(body)
    if not m:
        return []

    dep_date = parse_flight_date(m.group("dep_date"))
    arr_date = parse_flight_date(m.group("arr_date"))
    if not dep_date or not arr_date:
        return []

    dep_dt = _build_datetime(dep_date, m.group("dep_time"))
    arr_dt = _build_datetime(arr_date, m.group("arr_time"))

    pnr_m = _PNR_RE.search(body)
    booking_ref = (pnr_m.group(1) or pnr_m.group(2)) if pnr_m else ""

    pass_m = _PASSENGER_RE.search(body)
    passenger = pass_m.group(1).strip() if pass_m else ""

    seat_m = _SEAT_RE.search(body[body.find(m.group("fn")) :] if m.group("fn") in body else body)
    seat = seat_m.group(1).strip() if seat_m else ""

    flight = _make_flight_dict(
        rule,
        m.group("fn").replace(" ", ""),
        m.group("dep"),
        m.group("arr"),
        dep_dt,
        arr_dt,
        booking_ref,
        passenger,
    )
    if flight and seat:
        flight["seat"] = seat
    return [flight] if flight else []


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from an ITA Airways email."""
    body = email_msg.body or ""

    # The plain text is well-structured for the boarding-pass email
    flights = _extract_plain(body, rule)
    if flights:
        return flights

    # Try extracting text from the HTML body
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _extract_plain(html_text, rule)
        if flights:
            return flights

    return []
