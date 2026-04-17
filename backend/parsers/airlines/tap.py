"""
TAP Air Portugal (TP) flight extractor.

Five email formats are supported (tried in order):

1. HTML microdata (boarding pass) — schema.org meta tags with iataCode,
   flightNumber, departureTime, arrivalTime, airplaneSeat.
2. Check-in open — plain text with "HH:MM ARN" + "Date 01 Feb" blocks.
3. E-ticket receipt (RECIBO DE BILHETE ELETRÓNICO) — city names + TP781 + times.
4. Booking confirmation HTML — "Fri, 10 Nov\\n19:05\\nARN\\n22:35\\nLIS\\nTP 783".
5. HTML From/To — "Flight:\\nTP 82\\n...From:\\n...DD/MM/YYYY - HH:MM\\nTo:\\n..."
"""

import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    get_ref_year,
    make_flight_dict,
    parse_date,
    resolve_iata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Format 1: HTML microdata (boarding pass)
# ---------------------------------------------------------------------------


def _extract_html_microdata(html: str, rule, email_year: int) -> list[dict]:
    """Parse TAP boarding pass HTML using schema.org microdata."""
    soup = BeautifulSoup(html, "lxml")

    metas: list[tuple[str, str]] = [
        (str(m.get("itemprop", "")), str(m.get("content", "")))
        for m in soup.find_all("meta")
        if m.get("itemprop") and m.get("content")
    ]

    # Extract "DD/MM/YYYY - HH:MM" departure datetimes from "From:" blocks
    dep_datetime_re = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}:\d{2})")
    dep_datetimes: list[datetime] = []
    for m in dep_datetime_re.finditer(html):
        context = html[max(0, m.start() - 400) : m.start()]
        if context.rfind("From:") >= context.rfind("To:"):
            dep_date = parse_date(m.group(1), email_year)
            if dep_date:
                full_dt = _build_datetime(dep_date, m.group(2))
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
            dep_time_raw = arr_time_raw = seat = passenger = ""

            while j < len(metas):
                p2, v2 = metas[j]
                if p2 == "reservationNumber" and j > i:
                    break
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

            # iata_codes: [airline, departure, arrival]
            if len(iata_codes) < 3 or not fn_digits:
                i = j
                continue

            airline_code = iata_codes[0]
            dep_iata, arr_iata = iata_codes[1], iata_codes[2]
            flight_number = f"{airline_code}{fn_digits}"

            # Arrival from ISO string
            arr_dt: datetime | None = None
            if arr_time_raw:
                try:
                    arr_dt = datetime.fromisoformat(arr_time_raw).replace(tzinfo=UTC)
                except ValueError:
                    arr_date = parse_date(arr_time_raw, email_year)
                    arr_dt = _build_datetime(arr_date, "00:00") if arr_date else None
            if not arr_dt:
                i = j
                continue

            # Departure from span datetime
            dep_dt: datetime | None = None
            if leg_idx < len(dep_datetimes):
                dep_dt = dep_datetimes[leg_idx]
            else:
                dep_date = parse_date(dep_time_raw, email_year)
                dep_dt = _build_datetime(dep_date, "00:00") if dep_date else None
            if not dep_dt:
                i = j
                continue

            flight = make_flight_dict(
                rule,
                flight_number,
                dep_iata,
                arr_iata,
                dep_dt,
                arr_dt,
                booking_ref,
                passenger,
            )
            if flight and seat:
                flight["seat"] = seat
            if flight:
                flights.append(flight)

            leg_idx += 1
            i = j
        else:
            i += 1

    return flights


# ---------------------------------------------------------------------------
# Format 2: Check-in open email
# ---------------------------------------------------------------------------


def _extract_checkin(text: str, rule, email_year: int) -> list[dict]:
    """Parse TAP check-in email: "14:20 ARN ... Date 01 Feb ... Flight TP 781"."""
    fn_m = re.search(r"Flight\s*\n\s*(TP\s*\d{3,4})", text, re.IGNORECASE)
    if not fn_m:
        fn_m = re.search(r"\b(TP\s*\d{3,4})\b", text)
    if not fn_m:
        return []
    flight_number = fn_m.group(1).replace(" ", "")

    dep_m = re.search(
        r"(\d{2}:\d{2})\s+([A-Z]{3})\s*\n[\s\S]{0,80}?Date\s+(\d{1,2}\s+[A-Za-z]{3})",
        text,
    )
    arr_m = re.search(
        r"(\d{2}:\d{2})\s+([A-Z]{3})\s*\n[\s\S]{0,80}?Date\s+(\d{1,2}\s+[A-Za-z]{3})",
        text[dep_m.end() :] if dep_m else text,
    )
    if not dep_m or not arr_m:
        return []

    dep_date = parse_date(dep_m.group(3), email_year)
    arr_date = parse_date(arr_m.group(3), email_year) if arr_m else dep_date
    if not dep_date or not arr_date:
        return []

    flight = make_flight_dict(
        rule,
        flight_number,
        dep_m.group(2),
        arr_m.group(2),
        _build_datetime(dep_date, dep_m.group(1)),
        _build_datetime(arr_date, arr_m.group(1)),
    )
    return [flight] if flight else []


# ---------------------------------------------------------------------------
# Format 3: E-ticket receipt (RECIBO DE BILHETE ELETRÓNICO)
# ---------------------------------------------------------------------------

_eticket_leg_re = re.compile(
    r"([A-Z][A-Z ]{3,})\n"
    r"Terminal\s*/\s*Terminal:\s*\S+\n"
    r"\n"
    r"([A-Z][A-Z ]{3,})\n"
    r"Terminal\s*/\s*Terminal:\s*\S+\n"
    r"\n"
    r"(TP\d{2,4})\n"
    r"\n"
    r"(\d{2}:\d{2})\n"
    r"(\d{1,2}\w{3}\d{4})\n"
    r"\n"
    r"(\d{2}:\d{2})\n"
    r"(\d{1,2}\w{3}\d{4})\n",
)


def _extract_eticket_receipt(text: str, rule, email_year: int) -> list[dict]:
    """Parse TAP e-ticket receipt with city names + TP flight number + times."""
    if "RECIBO DE BILHETE" not in text.upper() and "ELECTRONIC TICKET RECEIPT" not in text.upper():
        return []

    flights = []
    for m in _eticket_leg_re.finditer(text):
        dep_iata = resolve_iata(m.group(1).strip())
        arr_iata = resolve_iata(m.group(2).strip())
        if not dep_iata or not arr_iata:
            logger.debug(
                "TAP eticket: could not resolve IATA for '%s' or '%s'",
                m.group(1).strip(),
                m.group(2).strip(),
            )
            continue

        dep_date = parse_date(m.group(5), email_year)
        arr_date = parse_date(m.group(7), email_year)
        if not dep_date or not arr_date:
            continue

        flight = make_flight_dict(
            rule,
            m.group(3).upper(),
            dep_iata,
            arr_iata,
            _build_datetime(dep_date, m.group(4)),
            _build_datetime(arr_date, m.group(6)),
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Format 4: Booking confirmation HTML
# ---------------------------------------------------------------------------

_weekday_prefixed_leg_re = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(\d{1,2}\s+\w{3})\n"
    r"(\d{2}:\d{2})\n"
    r"([A-Z]{3})\n"
    r"(\d{2}:\d{2})\n"
    r"([A-Z]{3})\n"
    r"[\s\S]{0,300}?\n"
    r"(TP\s*\d{3,4})\b",
    re.IGNORECASE,
)


def _extract_booking_confirmation_html(text: str, rule, email_year: int) -> list[dict]:
    """Parse TAP booking confirmation: "Fri, 10 Nov\\n19:05\\nARN\\n22:35\\nLIS\\n...TP 783"."""
    flights = []
    for m in _weekday_prefixed_leg_re.finditer(text):
        dep_date = parse_date(m.group(1), email_year)
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(2))
        arr_dt = _build_datetime(dep_date, m.group(4))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flight = make_flight_dict(
            rule,
            m.group(6).replace(" ", "").upper(),
            m.group(3).upper(),
            m.group(5).upper(),
            dep_dt,
            arr_dt,
        )
        if flight:
            flights.append(flight)
    return flights


# ---------------------------------------------------------------------------
# Format 5: HTML From/To blocks
# ---------------------------------------------------------------------------


def _extract_html_from_to(text: str, rule, email_year: int) -> list[dict]:
    """Parse multi-leg TAP boarding pass from BS4 text with From:/To: sections."""
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
        dep_date = parse_date(m.group(2), email_year)
        arr_date = parse_date(m.group(4), email_year)
        if not dep_date or not arr_date:
            continue

        # Look for IATA codes in parentheses within the match
        chunk_iata = re.findall(r"\(([A-Z]{3})\)", m.group(0))
        if len(chunk_iata) < 2:
            continue

        flight = make_flight_dict(
            rule,
            fn,
            chunk_iata[0],
            chunk_iata[1],
            _build_datetime(dep_date, m.group(3)),
            _build_datetime(arr_date, m.group(5)),
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a TAP Air Portugal email (tries 5 formats in order)."""
    body = email_msg.body or ""
    html = email_msg.html_body or ""
    email_year = get_ref_year(email_msg)

    # Format 1: HTML microdata
    if html:
        flights = _extract_html_microdata(html, rule, email_year)
        if flights:
            return flights

    # Format 2: check-in
    flights = _extract_checkin(body, rule, email_year)
    if flights:
        return enrich_flights(flights, body, email_msg.subject)

    # Format 3: e-ticket receipt
    flights = _extract_eticket_receipt(body, rule, email_year)
    if flights:
        return enrich_flights(flights, body, email_msg.subject)

    # Formats 4 & 5: HTML-based
    if html:
        soup = BeautifulSoup(html, "lxml")
        html_text = soup.get_text(separator="\n", strip=True)

        flights = _extract_booking_confirmation_html(html_text, rule, email_year)
        if flights:
            return enrich_flights(flights, html_text, email_msg.subject)

        flights = _extract_html_from_to(html_text, rule, email_year)
        if flights:
            return enrich_flights(flights, html_text, email_msg.subject)

    return []
