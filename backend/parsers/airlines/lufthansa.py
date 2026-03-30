"""
Lufthansa flight extractor (BS4 only — no plain-text regex fallback needed).

Handles four confirmed email formats:
  1. Standard e-ticket / itinerary (lufthansa.com):
       "16 Mar 2026  10:00  (FRA) ... LH1234 ... 11:50  (LHR)"
  2. Booking details (booking.lufthansa.com):
       "Fri. 29 March 2024: Stockholm – Frankfurt 06:45 h ... (ARN) ... 09:00 h ... (FRA) ... LH 809"
  3. Mobile boarding pass / check-in confirmed (lufthansa.com):
       "LH803\nFlight\n24JAN19\nDate\nARN\n...\nFRA\n...\n14:00\nPartida\nVT353Y\nCódigo da reserva"
  4. Check-in available notification (your.lufthansa-group.com):
       "ARN\n–\nFRA\n...\nLH803\n24.01.2019\nData\n...\n14:00\nPartida\n16:05\nChegada"
"""

import re
from datetime import date

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _extract_booking_reference,
    _get_text,
    _make_flight_dict,
    fix_overnight,
    normalize_fn,
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
                flight_number = normalize_fn(fn_m.group(1))
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
        arr_dt = fix_overnight(dep_dt, arr_dt)
        fn = normalize_fn(m.group(6))
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


# ---------------------------------------------------------------------------
# Format 3: mobile boarding pass / check-in confirmed (lufthansa.com)
#   "LH803\nFlight\n24JAN19\nDate\nARN\n...\nFRA\n...\n14:00\nPartida\nVT353Y\nCódigo"
# ---------------------------------------------------------------------------

_LH_BP_FN_DATE_RE = re.compile(
    r"(LH[\s\xa0]*\d{3,5})\n"  # g1: flight number
    r"(?:Flight|Voo)\n"
    r"(\d{2}[A-Z]{3}\d{2,4})\n"  # g2: date "24JAN19"
    r"(?:Date|Data)\n"
    r"([A-Z]{3})\n"  # g3: dep IATA
    r"[^\n]+\n"  # city name
    r"([A-Z]{3})\n"  # g4: arr IATA
)
_LH_BP_DEP_TIME_RE = re.compile(r"(\d{2}:\d{2})\n(?:Partida|Departure|Abflug)\b")
_LH_BP_REF_RE = re.compile(
    r"([A-Z0-9]{5,8})\n(?:C[óo]digo\s+da\s+reserva|Booking\s+(?:code|reference)|Buchungscode)",
    re.IGNORECASE,
)


def _extract_f3(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 3: Lufthansa mobile boarding pass / check-in confirmed."""
    flights = []
    for m in _LH_BP_FN_DATE_RE.finditer(text):
        fn = normalize_fn(m.group(1))
        dep_date = parse_flight_date(m.group(2))
        if not dep_date:
            continue
        dep_iata = m.group(3)
        arr_iata = m.group(4)
        # Departure time appears later: "14:00\nPartida"
        chunk = text[m.end() :]
        dep_time_m = _LH_BP_DEP_TIME_RE.search(chunk[:2000])
        if not dep_time_m:
            continue
        dep_dt = _build_datetime(dep_date, dep_time_m.group(1))
        if not dep_dt:
            continue
        # No arrival time in this format — use dep_dt as placeholder
        ref = booking_ref
        if not ref:
            ref_m = _LH_BP_REF_RE.search(chunk[:500])
            ref = ref_m.group(1) if ref_m else ""
        flight = _make_flight_dict(rule, fn, dep_iata, arr_iata, dep_dt, dep_dt, ref)
        if flight:
            flights.append(flight)
    return flights


# ---------------------------------------------------------------------------
# Format 4: check-in available notification (your.lufthansa-group.com)
#   "ARN\n–\nFRA\n...\nLH803\n24.01.2019\nData\n...\n14:00\nPartida\n16:05\nChegada"
# ---------------------------------------------------------------------------

_LH_CHECKIN_LEG_RE = re.compile(
    r"[A-Za-z][A-Za-z /.-]+\n"  # dep city name
    r"([A-Z]{3})\n"  # g1: dep IATA
    r"[–\-]\n"  # separator
    r"[A-Za-z][A-Za-z /.-]+\n"  # arr city name
    r"([A-Z]{3})\n"  # g2: arr IATA
    r"(?:[^\n]+\n){0,8}"  # duplicate city / expanded names
    r"(LH[\s\xa0]*\d{3,5})\n"  # g3: flight number
    r"(\d{2}\.\d{2}\.\d{4})\n"  # g4: date "24.01.2019"
    r"(?:Data|Date|Datum)\n"
    r"(?:[^\n]+\n){0,3}"  # class/other lines
    r"(\d{2}:\d{2})\n"  # g5: dep time
    r"(?:Partida|Departure|Abflug)\n"
    r"(\d{2}:\d{2})\n"  # g6: arr time
    r"(?:Chegada|Arrival|Ankunft)\n",
)
_DDMMYYYY_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def _parse_ddmmyyyy(s: str) -> date | None:
    m = _DDMMYYYY_RE.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _extract_f4(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 4: Lufthansa check-in available (your.lufthansa-group.com)."""

    flights = []
    for m in _LH_CHECKIN_LEG_RE.finditer(text):
        dep_date = _parse_ddmmyyyy(m.group(4))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(5))
        arr_dt = _build_datetime(dep_date, m.group(6))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        fn = normalize_fn(m.group(3))
        flight = _make_flight_dict(rule, fn, m.group(1), m.group(2), dep_dt, arr_dt, booking_ref)
        if flight:
            flights.append(flight)
    return flights


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a Lufthansa HTML email."""
    soup = BeautifulSoup(html, "lxml")
    # Space-separated text for formats 1 & 2 (their regexes use \s+ between tokens)
    text = _get_text(soup)
    # Newline-separated text for formats 3 & 4 (structured line-by-line)
    text_nl = soup.get_text(separator="\n", strip=True)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    # Try format 1 first (standard e-ticket)
    flights = _extract_f1(text, rule, booking_ref)
    if flights:
        return flights

    # Format 2: booking.lufthansa.com "Booking details"
    flights = _extract_f2(text, rule, booking_ref)
    if flights:
        return flights

    # Format 3: mobile boarding pass / check-in confirmed
    flights = _extract_f3(text_nl, rule, booking_ref)
    if flights:
        return flights

    # Format 4: check-in available (your.lufthansa-group.com)
    return _extract_f4(text_nl, rule, booking_ref)


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML (BS4) only."""
    if email_msg.html_body:
        return extract_bs4(email_msg.html_body, rule, email_msg)
    return []
