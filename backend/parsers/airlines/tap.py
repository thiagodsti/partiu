"""
TAP Air Portugal (TP) flight extractor.

Two email formats are supported:

1. Check-in open email (@flytap.com, "Online check-in here"):
   Plain text structure:
     Booking reference
     P6ANPW
     ...
     14:20 ARN
     ( Estocolmo /)
     Date  01 Feb
     ...
     17:45 LIS
     ( Lisboa)
     Date  01 Feb
     ...
     Flight
     TP  781

   The date is partial (DD Mon, no year). Year must be derived from
   email_msg.date.year.

2. Boarding pass email (@flytap.com, "Your Boarding Pass Confirmation"):
   The plain-text body has airport names anonymized to "TEST PASSENGER".
   The HTML body has rich microdata with iataCode, reservationNumber,
   flightNumber, departureTime, arrivalTime, and airplaneSeat.

   HTML microdata structure (meta tags with itemprop):
     reservationNumber: P6ANPW
     flightNumber: 82              ← no "TP" prefix
     iataCode: TP                  ← airline
     iataCode: GRU                 ← departure
     departureTime: 23FEB
     iataCode: LIS                 ← arrival
     arrivalTime: 2024-02-24T05:15:00
     airplaneSeat: 34F
"""

import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from ..shared import _make_flight_dict

logger = logging.getLogger(__name__)

_MONTHS_SHORT = {
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


def _parse_date(s: str, default_year: int | None = None) -> datetime | None:
    """Parse various date formats → UTC datetime (midnight)."""
    s = s.strip()

    # ISO: 2024-02-24
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
        except ValueError:
            return None

    # DD/MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=UTC)
        except ValueError:
            return None

    # "01 Feb" with optional year
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3})(?:\s+(\d{4}))?$", s)
    if m:
        day = int(m.group(1))
        mon = _MONTHS_SHORT.get(m.group(2).lower())
        year = int(m.group(3)) if m.group(3) else default_year
        if mon and year:
            try:
                return datetime(year, mon, day, tzinfo=UTC)
            except ValueError:
                return None

    # "Thursday, February 1, 2024"
    m = re.match(
        r"(?:\w+,\s+)?(\w+)\s+(\d{1,2}),\s+(\d{4})",
        s,
        re.IGNORECASE,
    )
    if m:
        mon_name = m.group(1)[:3].lower()
        mon = _MONTHS_SHORT.get(mon_name)
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(2)), tzinfo=UTC)
            except ValueError:
                return None

    # "23FEB" or "23FEB2024"
    m = re.match(r"^(\d{1,2})([A-Z]{3})(\d{4})?$", s, re.IGNORECASE)
    if m:
        day = int(m.group(1))
        mon = _MONTHS_SHORT.get(m.group(2).lower())
        year = int(m.group(3)) if m.group(3) else default_year
        if mon and year:
            try:
                return datetime(year, mon, day, tzinfo=UTC)
            except ValueError:
                return None

    return None


def _build_dt(base: datetime, time_str: str) -> datetime | None:
    try:
        h, m = map(int, time_str.split(":"))
        return base.replace(hour=h, minute=m)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# HTML microdata parser (boarding pass format)
# ---------------------------------------------------------------------------


def _extract_html_microdata(html: str, rule, email_year: int) -> list[dict]:
    """
    Parse TAP boarding pass HTML using schema.org microdata.

    The microdata has departure DATE (e.g. "23FEB") but not departure TIME.
    Departure times appear in span tags as "DD/MM/YYYY - HH:MM".
    Arrival times are ISO datetimes in arrivalTime meta content.
    """
    soup = BeautifulSoup(html, "lxml")

    # Collect all itemprop meta tags in order
    metas: list[tuple[str, str]] = [
        (str(m.get("itemprop", "")), str(m.get("content", "")))
        for m in soup.find_all("meta")
        if m.get("itemprop") and m.get("content")
    ]

    # Extract "DD/MM/YYYY - HH:MM" departure date-time strings from HTML "From:" blocks.
    # Each "From:" section contains the departure datetime; "To:" sections contain arrival.
    # We look for "From:" within 400 chars before each datetime occurrence.
    dep_datetime_re = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}:\d{2})")
    dep_datetimes: list[datetime] = []
    for m in dep_datetime_re.finditer(html):
        # Check if this datetime is in a "From:" block
        context_before = html[max(0, m.start() - 400) : m.start()]
        # Find the last "From:" or "To:" label before this datetime
        last_from = context_before.rfind("From:")
        last_to = context_before.rfind("To:")
        if last_from >= last_to:  # "From:" appears after "To:" → this is a departure time
            dt_base = _parse_date(m.group(1), email_year)
            if dt_base:
                full_dt = _build_dt(dt_base, m.group(2))
                if full_dt:
                    dep_datetimes.append(full_dt)

    flights = []
    leg_idx = 0
    i = 0
    while i < len(metas):
        prop, val = metas[i]
        if prop == "reservationNumber":
            booking_ref = val
            j = i + 1
            fn_digits = ""
            airline_code = "TP"
            iata_codes: list[str] = []
            dep_time_raw = ""
            arr_time_raw = ""
            seat = ""
            passenger = ""

            while j < len(metas):
                p2, v2 = metas[j]
                if p2 == "reservationNumber" and j > i:
                    break  # Next reservation
                if p2 == "name" and not fn_digits and not passenger:
                    passenger = v2
                elif p2 == "flightNumber":
                    fn_digits = v2
                elif p2 == "iataCode":
                    iata_codes.append(v2)
                elif p2 == "departureTime":
                    dep_time_raw = v2
                elif p2 == "arrivalTime":
                    arr_time_raw = v2
                elif p2 == "airplaneSeat":
                    seat = v2
                j += 1

            # iata_codes[0] = airline, [1] = departure, [2] = arrival
            if len(iata_codes) >= 3:
                airline_code = iata_codes[0]
                dep_iata = iata_codes[1]
                arr_iata = iata_codes[2]
            else:
                i = j
                continue

            if not fn_digits or not dep_iata or not arr_iata:
                i = j
                continue

            flight_number = f"{airline_code}{fn_digits}"

            # Arrival datetime from ISO string
            arr_dt: datetime | None = None
            if arr_time_raw:
                try:
                    arr_dt = datetime.fromisoformat(arr_time_raw).replace(tzinfo=UTC)
                except ValueError:
                    arr_dt = _parse_date(arr_time_raw, email_year)

            if not arr_dt:
                i = j
                continue

            # Departure datetime: use the leg_idx-th span datetime
            dep_dt: datetime | None = None
            if leg_idx < len(dep_datetimes):
                dep_dt = dep_datetimes[leg_idx]
            else:
                # Fallback: parse departure date from "23FEB" + set time to 00:00
                dep_date = _parse_date(dep_time_raw, email_year)
                dep_dt = dep_date

            if not dep_dt:
                i = j
                continue

            flight = _make_flight_dict(
                rule,
                flight_number,
                dep_iata,
                arr_iata,
                dep_dt,
                arr_dt,
                booking_ref,
                passenger,
            )
            if flight:
                if seat:
                    flight["seat"] = seat
                flights.append(flight)

            leg_idx += 1
            i = j
        else:
            i += 1

    return flights


# ---------------------------------------------------------------------------
# Plain text from HTML (boarding pass fallback using From:/To: labels)
# ---------------------------------------------------------------------------


def _extract_html_from_to(text: str, rule, email_year: int) -> list[dict]:
    """
    Parse multi-leg TAP boarding pass from BS4 text with From:/To: sections.

    Expected pattern per leg:
      Flight:\n{fn}\n...\nFrom:\n{city/airport}\n{terminal}\n{date} - {time}\nTo:\n{city/airport}\n{terminal}\n{date} - {time}
    """
    # Booking reference
    booking_m = re.search(
        r"(?:Booking\s+(?:Reference|TESTRF|[A-Z0-9]{5,8})[:  ]*\n\s*([A-Z0-9]{5,8})"
        r"|(?:Booking)\s*\n+\s*(?:TESTRF|[A-Z0-9]{5,8})\s*\n+\s*(?:Passenger)"
        r"|[Bb]ooking\s+(?:[Rr]eference)?[:\s]*\n\s*([A-Z0-9]{5,8}))",
        text,
    )
    booking_ref = ""
    if booking_m:
        booking_ref = next((g for g in booking_m.groups() if g), "")

    # Also try simpler pattern
    if not booking_ref:
        m = re.search(r"(?:Booking|PNR|Ref)[:\s\n]+([A-Z0-9]{5,8})", text, re.IGNORECASE)
        if m:
            booking_ref = m.group(1)

    # Find each flight block
    # Pattern: Flight:\n{fn}\n...\nFrom:\n...\n{date} - {time}\nTo:\n...\n{date} - {time}
    leg_re = re.compile(
        r"Flight:\s*\n\s*(TP\s*\d{2,4})\s*\n"
        r"[\s\S]{0,100}?"
        r"From:\s*\n"
        r"[\s\S]{0,200}?"
        r"(\d{2}/\d{2}/\d{4})\s+-\s+(\d{2}:\d{2})\s*\n"
        r"To:\s*\n"
        r"[\s\S]{0,200}?"
        r"(\d{2}/\d{2}/\d{4})\s+-\s+(\d{2}:\d{2})",
        re.IGNORECASE,
    )

    flights = []
    for m in leg_re.finditer(text):
        fn = m.group(1).replace(" ", "")
        dep_date_str = m.group(2)
        dep_time = m.group(3)
        arr_date_str = m.group(4)
        arr_time = m.group(5)

        dep_date = _parse_date(dep_date_str, email_year)
        arr_date = _parse_date(arr_date_str, email_year)
        if not dep_date or not arr_date:
            continue

        dep_dt = _build_dt(dep_date, dep_time)
        arr_dt = _build_dt(arr_date, arr_time)
        if not dep_dt or not arr_dt:
            continue

        # Look for IATA codes in the chunk between this match and next
        chunk = m.group(0)
        chunk_iata = re.findall(r"\(([A-Z]{3})\)", chunk)

        dep_iata = arr_iata = ""
        if len(chunk_iata) >= 2:
            dep_iata = chunk_iata[0]
            arr_iata = chunk_iata[1]

        if not dep_iata or not arr_iata:
            logger.debug("TAP plain: no IATA codes found for flight %s", fn)
            continue

        flight = _make_flight_dict(
            rule,
            fn,
            dep_iata,
            arr_iata,
            dep_dt,
            arr_dt,
            booking_ref,
            "",
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Check-in email parser (plain text with IATA codes)
# ---------------------------------------------------------------------------


def _extract_checkin(text: str, rule, email_year: int) -> list[dict]:
    """
    Parse TAP check-in email plain text.

    Structure:
      Booking reference
      P6ANPW
      ...
      14:20 ARN
      ( Estocolmo /)
      Date  01 Feb
      ...
      17:45 LIS
      ( Lisboa)
      Date  01 Feb
      ...
      Flight
      TP  781
    """
    # Booking reference
    booking_m = re.search(
        r"Booking\s+reference\s*\n\s*([A-Z0-9]{5,8})",
        text,
        re.IGNORECASE,
    )
    booking_ref = booking_m.group(1).strip() if booking_m else ""

    # Flight number
    fn_m = re.search(r"Flight\s*\n\s*(TP\s*\d{3,4})", text, re.IGNORECASE)
    if not fn_m:
        fn_m = re.search(r"\b(TP\s*\d{3,4})\b", text)
    if not fn_m:
        return []
    flight_number = fn_m.group(1).replace(" ", "")

    # Find departure block: HH:MM IATA\n...\nDate  DD Mon
    dep_m = re.search(
        r"(\d{2}:\d{2})\s+([A-Z]{3})\s*\n"
        r"[\s\S]{0,80}?"
        r"Date\s+(\d{1,2}\s+[A-Za-z]{3})",
        text,
    )
    arr_m = re.search(
        r"(\d{2}:\d{2})\s+([A-Z]{3})\s*\n"
        r"[\s\S]{0,80}?"
        r"Date\s+(\d{1,2}\s+[A-Za-z]{3})",
        text[dep_m.end() :] if dep_m else text,
    )

    if not dep_m:
        return []

    dep_time = dep_m.group(1)
    dep_iata = dep_m.group(2)
    dep_date_str = dep_m.group(3)

    arr_time = arr_iata = arr_date_str = ""
    if arr_m:
        arr_time = arr_m.group(1)
        arr_iata = arr_m.group(2)
        arr_date_str = arr_m.group(3)

    if not arr_iata:
        return []

    dep_date = _parse_date(dep_date_str, email_year)
    arr_date = _parse_date(arr_date_str, email_year) if arr_date_str else dep_date
    if not dep_date or not arr_date:
        return []

    dep_dt = _build_dt(dep_date, dep_time)
    arr_dt = _build_dt(arr_date, arr_time)
    if not dep_dt or not arr_dt:
        return []

    flight = _make_flight_dict(
        rule,
        flight_number,
        dep_iata,
        arr_iata,
        dep_dt,
        arr_dt,
        booking_ref,
        "",
    )
    return [flight] if flight else []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a TAP Air Portugal email."""
    body = email_msg.body or ""
    html = email_msg.html_body or ""

    email_year = email_msg.date.year if email_msg.date else datetime.now(UTC).year

    # Try HTML microdata first (boarding pass format)
    if html:
        flights = _extract_html_microdata(html, rule, email_year)
        if flights:
            logger.debug("TAP: extracted %d flight(s) via HTML microdata", len(flights))
            # Attempt to fill departure times from plain text if not set
            return flights

    # Try check-in plain text format
    flights = _extract_checkin(body, rule, email_year)
    if flights:
        logger.debug("TAP: extracted %d flight(s) via check-in format", len(flights))
        return flights

    # Try HTML text with From:/To: labels
    if html:
        soup = BeautifulSoup(html, "lxml")
        html_text = soup.get_text(separator="\n", strip=True)
        flights = _extract_html_from_to(html_text, rule, email_year)
        if flights:
            logger.debug("TAP: extracted %d flight(s) via From/To format", len(flights))
            return flights

    return []
