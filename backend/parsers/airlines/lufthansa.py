"""
Lufthansa flight extractor (BS4 only — no plain-text regex fallback needed).

Handles four confirmed email formats:
  1. Standard e-ticket / itinerary (lufthansa.com):
       "16 Mar 2026  10:00  (FRA) ... LH1234 ... 11:50  (LHR)"
  2. Booking details (booking.lufthansa.com):
       "Fri. 29 March 2024: Stockholm – Frankfurt 06:45 h ... (ARN) ... 09:00 h ... (FRA) ... LH 809"
  3. Mobile boarding pass / check-in confirmed (lufthansa.com):
       "LH803\\nFlight\\n24JAN19\\nDate\\nARN\\n...\\nFRA\\n...\\n14:00\\nPartida\\nVT353Y\\nCódigo da reserva"
  4. Check-in available notification (your.lufthansa-group.com):
       "ARN\\n–\\nFRA\\n...\\nLH803\\n24.01.2019\\nData\\n...\\n14:00\\nPartida\\n16:05\\nChegada"
"""

import re
from datetime import date

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _get_text,
    extract_booking_reference,
    fix_overnight,
    make_flight_dict,
    normalize_fn,
)

# ---------------------------------------------------------------------------
# Format 1: standard e-ticket  (date + time + (IATA) triplets)
# ---------------------------------------------------------------------------
_date_fragment = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
_time_fragment = r"(\d{1,2}:\d{2})"
_airport_fragment = r"\(([A-Z]{3})\)"
_date_time_airport_re = re.compile(
    _date_fragment + r"\s+" + _time_fragment + r".*?" + _airport_fragment,
    re.DOTALL,
)
_flight_number_re = re.compile(r"(LH[\s\xa0]*\d{3,5})")

# ---------------------------------------------------------------------------
# Format 2: booking.lufthansa.com "Booking details" emails
# ---------------------------------------------------------------------------
_booking_leg_re = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.\s+"
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}):"  # g1: date
    r".*?"
    r"(\d{1,2}:\d{2})\s+h"  # g2: dep time
    r".*?"
    r"\(([A-Z]{3})\)"  # g3: dep airport
    r".*?"
    r"(\d{1,2}:\d{2})\s+h"  # g4: arr time
    r".*?"
    r"\(([A-Z]{3})\)"  # g5: arr airport
    r".*?"
    r"(LH[\s\xa0]*\d{3,5})",  # g6: flight number
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Format 3: mobile boarding pass / check-in confirmed
# ---------------------------------------------------------------------------
_boarding_pass_flight_date_re = re.compile(
    r"(LH[\s\xa0]*\d{3,5})\n"
    r"(?:Flight|Voo)\n"
    r"(\d{2}[A-Z]{3}\d{2,4})\n"  # date "24JAN19"
    r"(?:Date|Data)\n"
    r"([A-Z]{3})\n"  # dep IATA
    r"[^\n]+\n"  # city name
    r"([A-Z]{3})\n"  # arr IATA
)
_boarding_pass_departure_time_re = re.compile(r"(\d{2}:\d{2})\n(?:Partida|Departure|Abflug)\b")
_boarding_pass_booking_ref_re = re.compile(
    r"([A-Z0-9]{5,8})\n(?:C[óo]digo\s+da\s+reserva|Booking\s+(?:code|reference)|Buchungscode)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Format 4: check-in available notification
# ---------------------------------------------------------------------------
_checkin_leg_re = re.compile(
    r"[A-Za-z][A-Za-z /.-]+\n"  # dep city name
    r"([A-Z]{3})\n"  # g1: dep IATA
    r"[–\-]\n"  # separator
    r"[A-Za-z][A-Za-z /.-]+\n"  # arr city name
    r"([A-Z]{3})\n"  # g2: arr IATA
    r"(?:[^\n]+\n){0,8}"
    r"(LH[\s\xa0]*\d{3,5})\n"  # g3: flight number
    r"(\d{2}\.\d{2}\.\d{4})\n"  # g4: date "24.01.2019"
    r"(?:Data|Date|Datum)\n"
    r"(?:[^\n]+\n){0,3}"
    r"(\d{2}:\d{2})\n"  # g5: dep time
    r"(?:Partida|Departure|Abflug)\n"
    r"(\d{2}:\d{2})\n"  # g6: arr time
    r"(?:Chegada|Arrival|Ankunft)\n",
)
_date_ddmmyyyy_re = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def _parse_ddmmyyyy(s: str) -> date | None:
    m = _date_ddmmyyyy_re.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Format extractors (each returns list[dict])
# ---------------------------------------------------------------------------


def _extract_f1(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 1: standard e-ticket with date+time+(IATA) triplets."""
    dta_matches = list(_date_time_airport_re.finditer(text))
    fn_matches = list(_flight_number_re.finditer(text))

    flights = []
    for i in range(0, len(dta_matches) - 1, 2):
        dep_m, arr_m = dta_matches[i], dta_matches[i + 1]
        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue

        fn = ""
        for fn_m in fn_matches:
            if dep_m.start() <= fn_m.start() <= arr_m.start():
                fn = normalize_fn(fn_m.group(1))
                break

        flight = make_flight_dict(
            rule,
            fn,
            dep_m.group(3),
            arr_m.group(3),
            _build_datetime(dep_date, dep_m.group(2)),
            _build_datetime(arr_date, arr_m.group(2)),
            booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


def _extract_f2(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 2: booking.lufthansa.com 'Booking details' with 'HH:MM h' times."""
    flights = []
    for m in _booking_leg_re.finditer(text):
        dep_date = parse_flight_date(m.group(1))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(2))
        arr_dt = _build_datetime(dep_date, m.group(4))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flight = make_flight_dict(
            rule,
            normalize_fn(m.group(6)),
            m.group(3),
            m.group(5),
            dep_dt,
            arr_dt,
            booking_ref,
        )
        if flight:
            flights.append(flight)
    return flights


def _extract_f3(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 3: Lufthansa mobile boarding pass / check-in confirmed."""
    flights = []
    for m in _boarding_pass_flight_date_re.finditer(text):
        fn = normalize_fn(m.group(1))
        dep_date = parse_flight_date(m.group(2))
        if not dep_date:
            continue
        # Departure time appears later: "14:00\nPartida"
        chunk = text[m.end() :]
        dep_time_m = _boarding_pass_departure_time_re.search(chunk[:2000])
        if not dep_time_m:
            continue
        dep_dt = _build_datetime(dep_date, dep_time_m.group(1))
        if not dep_dt:
            continue
        # No arrival time in this format — use dep_dt as placeholder
        ref = booking_ref
        if not ref:
            ref_m = _boarding_pass_booking_ref_re.search(chunk[:500])
            ref = ref_m.group(1) if ref_m else ""
        flight = make_flight_dict(rule, fn, m.group(3), m.group(4), dep_dt, dep_dt, ref)
        if flight:
            flights.append(flight)
    return flights


def _extract_f4(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 4: Lufthansa check-in available (your.lufthansa-group.com)."""
    flights = []
    for m in _checkin_leg_re.finditer(text):
        dep_date = _parse_ddmmyyyy(m.group(4))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(5))
        arr_dt = _build_datetime(dep_date, m.group(6))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flight = make_flight_dict(
            rule,
            normalize_fn(m.group(3)),
            m.group(1),
            m.group(2),
            dep_dt,
            arr_dt,
            booking_ref,
        )
        if flight:
            flights.append(flight)
    return flights


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a Lufthansa HTML email (tries all 4 formats)."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)  # space-separated (formats 1 & 2)
    text_nl = soup.get_text(separator="\n", strip=True)  # newline-separated (formats 3 & 4)
    booking_ref = extract_booking_reference(text, email_msg.subject or "")

    for extractor in (_extract_f1, _extract_f2):
        flights = extractor(text, rule, booking_ref)
        if flights:
            return flights

    for extractor in (_extract_f3, _extract_f4):
        flights = extractor(text_nl, rule, booking_ref)
        if flights:
            return flights

    return []


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML (BS4) only."""
    if email_msg.html_body:
        return extract_bs4(email_msg.html_body, rule, email_msg)
    return []
