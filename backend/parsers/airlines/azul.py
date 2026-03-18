"""
Azul Brazilian Airlines flight extractor (BS4 only).
"""

import re
from datetime import date as date_type
from datetime import datetime

from bs4 import BeautifulSoup

from ..shared import (
    _build_datetime,
    _extract_booking_reference,
    _get_text,
    _make_flight_dict,
)


def _parse_ddmm(date_str: str, ref_year: int, email_date=None) -> date_type | None:
    """
    Parse a DD/MM date string and infer the year from context.
    If the resulting date is before the email date, bumps the year by 1.
    """
    m = re.match(r"(\d{2})/(\d{2})", date_str)
    if not m:
        return None
    try:
        day, month = int(m.group(1)), int(m.group(2))
        candidate = date_type(ref_year, month, day)
        if email_date and candidate < email_date.date():
            candidate = date_type(ref_year + 1, month, day)
        return candidate
    except ValueError:
        return None


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from an Azul HTML email."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)
    ref_year = email_msg.date.year if email_msg.date else datetime.now().year

    # Each flight block looks like:
    #   GRU  DD/MM • HH:MM  ... Voo 1234 ...  CGH  DD/MM • HH:MM
    block_re = re.compile(
        r"(?:^|\s)([A-Z]{3})\s"
        r".*?"
        r"(\d{2}/\d{2})\s*[•·]\s*"
        r"(\d{1,2}:\d{2})"
        r".*?"
        r"(?:Voo|Flight)\s+(\d{3,5})"
        r".*?"
        r"(?:^|\s)([A-Z]{3})\s"
        r".*?"
        r"(\d{2}/\d{2})\s*[•·]\s*"
        r"(\d{1,2}:\d{2})",
        re.DOTALL | re.MULTILINE,
    )

    flights = []
    for m in block_re.finditer(text):
        dep_airport = m.group(1)
        dep_date = _parse_ddmm(m.group(2), ref_year, email_msg.date)
        dep_time = m.group(3)
        flight_number = f"{rule.airline_code}{m.group(4)}"
        arr_airport = m.group(5)
        arr_date = _parse_ddmm(m.group(6), ref_year, email_msg.date)
        arr_time = m.group(7)

        if not dep_date or not arr_date:
            continue

        flight = _make_flight_dict(
            rule, flight_number,
            dep_airport, arr_airport,
            _build_datetime(dep_date, dep_time),
            _build_datetime(arr_date, arr_time),
            booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights
