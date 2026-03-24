"""
SAS Scandinavian Airlines flight extractor.

Two extraction strategies:
  1. extract_bs4()   — HTML email parsed with BeautifulSoup.
  2. extract_regex() — plain-text fallback (PDF tabular or "Din resa" block style).

The regex extractor is also reused by Norwegian (similar email format).
"""

import logging
import re
from datetime import date as date_type
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from ..engine import MONTH_MAP, parse_flight_date
from ..shared import (
    _build_datetime,
    _extract_booking_reference,
    _get_text,
    _make_aware,
    _make_flight_dict,
)

logger = logging.getLogger(__name__)

# Flight number prefixes for SAS and its codeshare / Star Alliance partners
_FLIGHT_NUM_CODES = r"(?:SK|DY|D8|VS|LH|LX|OS|TP|A3|SN|BA|AF)"

# Well-known airport name → IATA code mappings used by SAS/Amadeus e-tickets.
# The DB is queried as a final fallback when a name is not in this table.
_KNOWN_AIRPORTS: dict[str, str] = {
    "stockholm arlanda": "ARN",
    "london heathrow": "LHR",
    "london gatwick": "LGW",
    "london city": "LCY",
    "london stansted": "STN",
    "london luton": "LTN",
    "paris charles de gaulle": "CDG",
    "paris orly": "ORY",
    "copenhagen kastrup": "CPH",
    "oslo gardermoen": "OSL",
    "oslo airport": "OSL",
    "oslo lufthavn": "OSL",
    "gothenburg landvetter": "GOT",
    "bergen flesland": "BGO",
    "helsinki vantaa": "HEL",
    "amsterdam schiphol": "AMS",
    "frankfurt": "FRA",
    "munich": "MUC",
    "zurich": "ZRH",
    "brussels": "BRU",
    "vienna": "VIE",
    "lisbon": "LIS",
    "dublin": "DUB",
    "madrid": "MAD",
    "barcelona": "BCN",
    "rome fiumicino": "FCO",
    "milan malpensa": "MXP",
    "new york jfk": "JFK",
    "new york newark": "EWR",
    "los angeles": "LAX",
    "chicago": "ORD",
    "cape town": "CPT",
    "johannesburg": "JNB",
    "tokyo narita": "NRT",
    "tokyo haneda": "HND",
    "bangkok": "BKK",
    "singapore": "SIN",
    "hong kong": "HKG",
    "shanghai pudong": "PVG",
    "beijing": "PEK",
    "dubai": "DXB",
    "doha": "DOH",
    "istanbul": "IST",
    # Common short-names used in SAS e-tickets
    "arlanda": "ARN",
    "heathrow": "LHR",
    "gatwick": "LGW",
    "kastrup": "CPH",
    "gardermoen": "OSL",
    "landvetter": "GOT",
    "schiphol": "AMS",
    "fiumicino": "FCO",
    "malpensa": "MXP",
}


def _resolve_airport(text: str) -> str:
    """
    Resolve an IATA code from a SAS PDF airport/city string.

    Tries in order:
      1. Trailing 3-letter uppercase code in the string
      2. Exact match in the known-airports table
      3. Last word match in the known-airports table
      4. Database lookup by airport name / city name
    """
    # "Stockholm Arlanda ARN" → "ARN"
    m = re.search(r"\b([A-Z]{3})$", text)
    if m:
        return m.group(1)

    name_lower = text.lower().strip()
    if name_lower in _KNOWN_AIRPORTS:
        return _KNOWN_AIRPORTS[name_lower]

    words = text.split()
    if words and words[-1].lower() in _KNOWN_AIRPORTS:
        return _KNOWN_AIRPORTS[words[-1].lower()]

    try:
        from ...database import db_conn
        with db_conn() as conn:
            if len(words) > 1:
                row = conn.execute(
                    "SELECT iata_code FROM airports WHERE name LIKE ? LIMIT 1",
                    (f"%{words[-1]}%",),
                ).fetchone()
                if row:
                    return row["iata_code"]
            row = conn.execute(
                "SELECT iata_code FROM airports WHERE name LIKE ? OR city_name LIKE ? LIMIT 1",
                (f"%{name_lower}%", f"%{name_lower}%"),
            ).fetchone()
            if row:
                return row["iata_code"]
    except Exception:
        pass

    return ""


def _parse_route(route_text: str) -> tuple[str, str]:
    """
    Parse a SAS PDF route string like "Stockholm Arlanda - London Heathrow"
    into (dep_iata, arr_iata).
    """
    parts = re.split(r"\s+-\s+", route_text, maxsplit=1)
    if len(parts) != 2:
        return ("", "")
    return (_resolve_airport(parts[0].strip()), _resolve_airport(parts[1].strip()))


# ---------------------------------------------------------------------------
# BS4 extractor
# ---------------------------------------------------------------------------


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a SAS HTML email."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    date_re = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")
    route_re = re.compile(
        r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})"
    )
    time_re = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    flight_num_re = re.compile(rf"({_FLIGHT_NUM_CODES}\s*\d{{2,5}})")

    date_matches = list(date_re.finditer(text))
    flights = []

    for i, date_m in enumerate(date_matches):
        dep_date = parse_flight_date(date_m.group(1))
        if not dep_date:
            continue

        block_start = date_m.start()
        block_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(text)
        block = text[block_start:block_end]

        route_m = route_re.search(block)
        time_m = time_re.search(block)
        fn_m = flight_num_re.search(block)
        if not all([route_m, time_m, fn_m]):
            continue
        assert route_m is not None and time_m is not None and fn_m is not None

        dep_airport = route_m.group(1)
        arr_airport = route_m.group(2)
        dep_time = time_m.group(1)
        arr_time = time_m.group(2)
        flight_number = fn_m.group(1).replace(" ", "")

        dep_dt = _build_datetime(dep_date, dep_time)
        arr_dt = _build_datetime(dep_date, arr_time)

        # Handle overnight flights
        if arr_dt and dep_dt and arr_dt < dep_dt:
            arr_dt = _build_datetime(dep_date + timedelta(days=1), arr_time)

        flight = _make_flight_dict(rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref)
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Regex fallback extractor
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML (BS4), then plain-text regex."""
    if email_msg.html_body:
        result = extract_bs4(email_msg.html_body, rule, email_msg)
        if result:
            return result
    return extract_regex(email_msg, rule)


def extract_regex(email_msg, rule) -> list[dict]:
    """
    Plain-text regex fallback for SAS (and Norwegian) emails.

    Tries the PDF tabular format first, then falls back to the
    "Din resa" / HTML-to-text block style.
    """
    body = email_msg.body
    booking_ref = _booking_ref_from_text(email_msg.subject + "\n" + body)
    passenger = _passenger_from_text(body)

    flights = _extract_pdf_tabular(body, email_msg, rule, booking_ref, passenger)
    if flights:
        return flights

    return _extract_block_style(body, rule, booking_ref)


def _booking_ref_from_text(text: str) -> str:
    m = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|Buchungscode|confirmation\s*code)[:\s\[]+([A-Z0-9]{5,8})",
        text, re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _passenger_from_text(body: str) -> str:
    m = re.search(
        r"(?:Mr|Mrs|Ms|Miss)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)\s+Date\s+of\s+Issue",
        body, re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _extract_pdf_tabular(body, email_msg, rule, booking_ref, passenger) -> list[dict]:
    """
    Parse the compact tabular format found in SAS PDF / e-ticket emails:
      SK1829 / 16MAR  Stockholm Arlanda - London Heathrow  10:00  11:50
    """
    pdf_line_re = re.compile(
        rf"(?P<flight_number>{_FLIGHT_NUM_CODES}\s*\d{{2,5}})"
        r"\s*/\s*"
        r"(?P<day>\d{1,2})(?P<month>[A-Z]{3})"
        r"\s+"
        r"(?P<route>.+?)"
        r"\s+"
        r"(?P<dep_time>\d{1,2}:\d{2})"
        r"\s+"
        r"(?P<arr_time>\d{1,2}:\d{2})"
        r"(?:\s+\d{1,2}:\d{2})?"
        r"(?:\s+Terminal\s+(?P<terminal>\S+))?",
        re.IGNORECASE,
    )

    pdf_matches = list(pdf_line_re.finditer(body))
    if not pdf_matches:
        return []

    ref_year = email_msg.date.year if email_msg.date else datetime.now().year
    flights = []

    for m in pdf_matches:
        flight_number = m.group("flight_number").strip().replace(" ", "")
        day = int(m.group("day"))
        month_num = MONTH_MAP.get(m.group("month").lower())
        if not month_num:
            continue

        try:
            flight_date = date_type(ref_year, month_num, day)
        except ValueError:
            continue

        # If the parsed date is before the email date, it's probably next year
        if email_msg.date and flight_date < email_msg.date.date():
            try:
                flight_date = date_type(ref_year + 1, month_num, day)
            except ValueError:
                continue

        dep_airport, arr_airport = _parse_route(m.group("route").strip())
        if not dep_airport or not arr_airport:
            continue

        dep_time_str = m.group("dep_time")
        arr_time_str = m.group("arr_time")
        terminal = m.group("terminal") or ""

        dep_h, dep_m_val = map(int, dep_time_str.split(":"))
        arr_h, arr_m_val = map(int, arr_time_str.split(":"))

        dep_dt = _make_aware(datetime(flight_date.year, flight_date.month, flight_date.day, dep_h, dep_m_val))

        arr_date = flight_date
        if arr_h < dep_h or (arr_h == dep_h and arr_m_val < dep_m_val):
            arr_date = flight_date + timedelta(days=1)
        arr_dt = _make_aware(datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val))

        base = _make_flight_dict(rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref, passenger)
        if base is None:
            continue
        flight = {**base, "departure_terminal": terminal}
        flights.append(flight)

    return flights


def _extract_block_style(body: str, rule, booking_ref: str) -> list[dict]:
    """
    Parse the "Din resa" / HTML-to-text block format:
      16 March 2026
      ARN – London Heathrow LHR
      SK1829  10:00 – 11:50
    """
    date_re = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")
    route_re = re.compile(
        r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})"
    )
    time_re = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    flight_num_re = re.compile(rf"({_FLIGHT_NUM_CODES}\s*\d{{2,5}})")

    date_matches = list(date_re.finditer(body))
    flights = []

    for i, date_m in enumerate(date_matches):
        dep_date = parse_flight_date(date_m.group(1))
        if not dep_date:
            continue

        block_start = date_m.start()
        block_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(body)
        block = body[block_start:block_end]

        routes = list(route_re.finditer(block))
        times = list(time_re.finditer(block))
        fns = list(flight_num_re.finditer(block))

        for j in range(min(len(routes), len(times), len(fns))):
            dep_airport = routes[j].group(1)
            arr_airport = routes[j].group(2)
            dep_time_str = times[j].group(1)
            arr_time_str = times[j].group(2)
            flight_number = fns[j].group(1).replace(" ", "")

            dep_h, dep_m_val = map(int, dep_time_str.split(":"))
            arr_h, arr_m_val = map(int, arr_time_str.split(":"))

            dep_dt = _make_aware(datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m_val))

            arr_date = dep_date
            if arr_h < dep_h or (arr_h == dep_h and arr_m_val < dep_m_val):
                arr_date = dep_date + timedelta(days=1)
            arr_dt = _make_aware(datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val))

            flight = _make_flight_dict(rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref)
            if flight:
                flights.append(flight)

    return flights
