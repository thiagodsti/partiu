"""
Ryanair flight extractor.

Parses Ryanair "Travel Itinerary" HTML confirmation emails.

Email structure (after BS4 text extraction):
  Reservation:
  K1QU3R
  ...
  FR2878
  Milan (Bergamo)  -
  ARN
  Wed, 23 Apr 25
  Departure time -
  17:55
  Arrival time -
  20:35
  (BGY) -
  (ARN)
"""

import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BOOKING_RE = re.compile(
    r"Reserv\w*:\s*\n([A-Z0-9]{5,8})",
    re.IGNORECASE,
)
# Ryanair flight numbers: FR + 3-5 digits (also Lauda/Malta Air on FR code)
_FN_RE = re.compile(r"\b([A-Z]{2}\d{3,5})\b")
# "Wed, 23 Apr 25" or "Wed, 23 Apr 2025"
_DATE_RE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(\d{1,2}\s+\w{3}\s+\d{2,4})",
    re.IGNORECASE,
)
_DEP_TIME_RE = re.compile(r"Departure\s+time\s*[-–]\s*(\d{1,2}:\d{2})", re.IGNORECASE)
_ARR_TIME_RE = re.compile(r"Arrival\s+time\s*[-–]\s*(\d{1,2}:\d{2})", re.IGNORECASE)
# Pair of IATA codes like "(BGY) -\n(ARN)" or "(BGY)\n(ARN)"
_IATA_PAIR_RE = re.compile(
    r"\(([A-Z]{3})\)\s*[-–]?\s*\n\s*\(([A-Z]{3})\)",
    re.IGNORECASE,
)

# Months for date parsing
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _parse_date(date_str: str) -> datetime | None:
    """Parse '23 Apr 25' or '23 Apr 2025' → UTC datetime (midnight)."""
    parts = date_str.strip().split()
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        month = _MONTHS.get(parts[1][:3].lower())
        year = int(parts[2])
        if year < 100:
            year += 2000
        if not month:
            return None
        return datetime(year, month, day, 0, 0, tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _build_dt(base: datetime, time_str: str) -> datetime | None:
    """Combine a date-only datetime with 'HH:MM' time string."""
    try:
        h, m = map(int, time_str.split(":"))
        return base.replace(hour=h, minute=m)
    except (ValueError, TypeError):
        return None


def _extract_text(email_msg) -> str:
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        return soup.get_text(separator="\n", strip=True)
    return email_msg.body or ""


def extract(email_msg, rule) -> list[dict]:
    text = _extract_text(email_msg)

    booking_ref_m = _BOOKING_RE.search(text)
    booking_ref = booking_ref_m.group(1) if booking_ref_m else ""

    # Collect all flight number matches (deduplicated, preserving order)
    seen_fns: set[str] = set()
    flight_numbers: list[str] = []
    for m in _FN_RE.finditer(text):
        fn = m.group(1)
        if fn not in seen_fns:
            seen_fns.add(fn)
            flight_numbers.append(fn)

    if not flight_numbers:
        return []

    # Each leg has one date, one dep time, one arr time, one IATA pair
    dates = _DATE_RE.findall(text)
    dep_times = [m.group(1) for m in _DEP_TIME_RE.finditer(text)]
    arr_times = [m.group(1) for m in _ARR_TIME_RE.finditer(text)]
    iata_pairs = [(m.group(1).upper(), m.group(2).upper()) for m in _IATA_PAIR_RE.finditer(text)]

    if not dates or not dep_times or not arr_times or not iata_pairs:
        logger.debug(
            "Ryanair: incomplete data — dates=%s dep=%s arr=%s iata=%s",
            dates,
            dep_times,
            arr_times,
            iata_pairs,
        )
        return []

    flights = []
    n_legs = min(len(flight_numbers), len(dates), len(dep_times), len(arr_times), len(iata_pairs))

    for i in range(n_legs):
        base_dt = _parse_date(dates[i])
        if not base_dt:
            continue
        dep_dt = _build_dt(base_dt, dep_times[i])
        arr_dt = _build_dt(base_dt, arr_times[i])
        if not dep_dt or not arr_dt:
            continue
        # Overnight flight: arrival before departure → add one day
        if arr_dt < dep_dt:
            from datetime import timedelta

            arr_dt = arr_dt + timedelta(days=1)

        dep_iata, arr_iata = iata_pairs[i]
        flights.append(
            {
                "airline_name": rule.airline_name,
                "airline_code": rule.airline_code,
                "flight_number": flight_numbers[i],
                "booking_reference": booking_ref,
                "departure_airport": dep_iata,
                "arrival_airport": arr_iata,
                "departure_datetime": dep_dt,
                "arrival_datetime": arr_dt,
                "passenger_name": "",
                "seat": "",
                "cabin_class": "",
            }
        )

    return flights
