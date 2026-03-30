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
    fix_overnight,
    normalize_fn,
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Flight number prefixes for SAS and its codeshare / Star Alliance partners
_FLIGHT_NUM_CODES = r"(?:SK|DY|D8|VS|LH|LX|OS|TP|A3|SN|BA|AF)"


def _parse_route(route_text: str) -> tuple[str, str]:
    """
    Parse a SAS PDF route string like "Stockholm Arlanda - London Heathrow"
    into (dep_iata, arr_iata).
    """
    parts = re.split(r"\s+-\s+", route_text, maxsplit=1)
    if len(parts) != 2:
        return ("", "")
    return (resolve_iata(parts[0].strip()), resolve_iata(parts[1].strip()))


# ---------------------------------------------------------------------------
# BS4 extractor
# ---------------------------------------------------------------------------


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a SAS HTML email."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    date_re = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")
    route_re = re.compile(r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})")
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

        fn_matches = list(flight_num_re.finditer(block))
        route_matches = list(route_re.finditer(block))
        time_matches = list(time_re.finditer(block))

        # Anchor on flight numbers to avoid picking up summary rows.
        # SAS emails start with a summary ("ARN–JNB 18:10–11:30 1 stopp")
        # before the individual legs. Finding the nearest route/time before
        # each flight number ensures we get per-leg data, not the summary.
        for fn_m in fn_matches:
            fn_pos = fn_m.start()

            route_m = next((r for r in reversed(route_matches) if r.start() < fn_pos), None)
            time_m = next((t for t in reversed(time_matches) if t.start() < fn_pos), None)
            if not route_m or not time_m:
                continue

            dep_airport = route_m.group(1)
            arr_airport = route_m.group(2)
            dep_time = time_m.group(1)
            arr_time = time_m.group(2)
            flight_number = normalize_fn(fn_m.group(1))

            dep_dt = _build_datetime(dep_date, dep_time)
            arr_dt = _build_datetime(dep_date, arr_time)

            if arr_dt and dep_dt:
                arr_dt = fix_overnight(dep_dt, arr_dt)

            flight = _make_flight_dict(
                rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref
            )
            if flight:
                flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Regex fallback extractor
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: HTML (BS4) → plain-text regex → PDF attachments."""
    if email_msg.html_body:
        result = extract_bs4(email_msg.html_body, rule, email_msg)
        if result:
            return result

    result = extract_regex(email_msg, rule)
    if result:
        return result

    # Some SAS e-ticket emails carry flight data only in a PDF attachment
    # (no usable HTML/text body). Try the SAS tabular PDF format directly.
    if email_msg.pdf_attachments:
        from ..email_connector import _extract_text_from_pdf

        for pdf_bytes in email_msg.pdf_attachments:
            pdf_text = _extract_text_from_pdf(pdf_bytes)
            if not pdf_text:
                continue
            booking_ref = _booking_ref_from_text(email_msg.subject + "\n" + pdf_text)
            passenger = _passenger_from_text(pdf_text)
            flights = _extract_pdf_tabular(pdf_text, email_msg, rule, booking_ref, passenger)
            if flights:
                return flights

    return []


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
        text,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _passenger_from_text(body: str) -> str:
    m = re.search(
        r"(?:Mr|Mrs|Ms|Miss)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)\s+Date\s+of\s+Issue",
        body,
        re.IGNORECASE,
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
        flight_number = normalize_fn(m.group("flight_number").strip())
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

        dep_dt = _make_aware(
            datetime(flight_date.year, flight_date.month, flight_date.day, dep_h, dep_m_val)
        )
        arr_date = flight_date
        if arr_h < dep_h or (arr_h == dep_h and arr_m_val < dep_m_val):
            arr_date = flight_date + timedelta(days=1)
        arr_dt = _make_aware(
            datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val)
        )

        base = _make_flight_dict(
            rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref, passenger
        )
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
    route_re = re.compile(r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})")
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
            flight_number = normalize_fn(fns[j].group(1))

            dep_h, dep_m_val = map(int, dep_time_str.split(":"))
            arr_h, arr_m_val = map(int, arr_time_str.split(":"))

            dep_dt = _make_aware(
                datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m_val)
            )

            arr_date = dep_date
            if arr_h < dep_h or (arr_h == dep_h and arr_m_val < dep_m_val):
                arr_date = dep_date + timedelta(days=1)
            arr_dt = _make_aware(
                datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val)
            )

            flight = _make_flight_dict(
                rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref
            )
            if flight:
                flights.append(flight)

    return flights
