"""
Lufthansa flight extractor (BS4 only — no plain-text regex fallback needed).

Handles two confirmed email formats:
  1. Standard e-ticket / itinerary (lufthansa.com):
       "16 Mar 2026  10:00  (FRA) ... LH1234 ... 11:50  (LHR)"
  2. Booking details (booking.lufthansa.com):
       "Fri. 29 March 2024: Stockholm – Frankfurt 06:45 h ... (ARN) ... 09:00 h ... (FRA) ... LH 809"
"""

import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _extract_booking_reference,
    _get_text,
    _make_flight_dict,
)

# ---------------------------------------------------------------------------
# Format 1: standard e-ticket  (date + time + (IATA) triplets)
# ---------------------------------------------------------------------------
_DATE_F1 = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
_TIME_F1 = r"(\d{1,2}:\d{2})"
_AIRPORT_F1 = r"\(([A-Z]{3})\)"
_DTA_RE = re.compile(_DATE_F1 + r"\s+" + _TIME_F1 + r".*?" + _AIRPORT_F1, re.DOTALL)
_FN_RE = re.compile(r"(LH[\s\xa0]*\d{3,5})")

# ---------------------------------------------------------------------------
# Format 2: booking.lufthansa.com "Booking details" emails
#   "Fri. 29 March 2024: City – City  06:45 h  City Name (ARN)  Terminal N
#    09:00 h  City Name (FRA)  Terminal N  LH 809"
# ---------------------------------------------------------------------------
_LH_BOOKING_LEG_RE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.\s+"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}):"  # g1: date "29 March 2024"
    r".*?"
    r"(\d{1,2}:\d{2})\s+h"  # g2: dep time "06:45"
    r".*?"
    r"\(([A-Z]{3})\)"  # g3: dep airport "(ARN)"
    r".*?"
    r"(\d{1,2}:\d{2})\s+h"  # g4: arr time "09:00"
    r".*?"
    r"\(([A-Z]{3})\)"  # g5: arr airport "(FRA)"
    r".*?"
    r"(LH[\s\xa0]*\d{3,5})",  # g6: flight number "LH 809"
    re.DOTALL,
)


def _extract_f1(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 1: standard e-ticket with date+time+(IATA) triplets."""
    dta_matches = list(_DTA_RE.finditer(text))
    fn_matches = list(_FN_RE.finditer(text))

    flights = []
    for i in range(0, len(dta_matches) - 1, 2):
        dep_m = dta_matches[i]
        arr_m = dta_matches[i + 1]

        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue

        dep_dt = _build_datetime(dep_date, dep_m.group(2))
        arr_dt = _build_datetime(arr_date, arr_m.group(2))

        flight_number = ""
        for fn_m in fn_matches:
            if dep_m.start() <= fn_m.start() <= arr_m.start():
                flight_number = fn_m.group(1).replace(" ", "").replace("\xa0", "")
                break

        flight = _make_flight_dict(
            rule,
            flight_number,
            dep_m.group(3),
            arr_m.group(3),
            dep_dt,
            arr_dt,
            booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


def _extract_f2(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 2: booking.lufthansa.com 'Booking details' with 'HH:MM h' times."""
    flights = []
    for m in _LH_BOOKING_LEG_RE.finditer(text):
        dep_date = parse_flight_date(m.group(1))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(2))
        arr_dt = _build_datetime(dep_date, m.group(4))
        if not dep_dt or not arr_dt:
            continue
        # Overnight: arrival before departure → add one day
        if arr_dt < dep_dt:
            from datetime import timedelta

            arr_dt = arr_dt + timedelta(days=1)
        fn = m.group(6).replace(" ", "").replace("\xa0", "")
        flight = _make_flight_dict(
            rule,
            fn,
            m.group(3),
            m.group(5),
            dep_dt,
            arr_dt,
            booking_ref,
        )
        if flight:
            flights.append(flight)
    return flights


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a Lufthansa HTML email."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    # Try format 1 first (standard e-ticket)
    flights = _extract_f1(text, rule, booking_ref)
    if flights:
        return flights

    # Fall back to format 2 (booking.lufthansa.com "Booking details")
    return _extract_f2(text, rule, booking_ref)


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML (BS4) only."""
    if email_msg.html_body:
        return extract_bs4(email_msg.html_body, rule, email_msg)
    return []
