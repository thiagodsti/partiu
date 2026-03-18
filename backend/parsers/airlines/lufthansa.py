"""
Lufthansa flight extractor (BS4 only — no plain-text regex fallback needed).
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


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a Lufthansa HTML email."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    _DATE = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
    _TIME = r"(\d{1,2}:\d{2})"
    _AIRPORT = r"\(([A-Z]{3})\)"

    # Each flight appears as two consecutive date/time/airport triplets:
    #   departure: "16 Mar 2026  10:00  (FRA)"
    #   arrival:   "16 Mar 2026  11:50  (LHR)"
    dta_re = re.compile(_DATE + r"\s+" + _TIME + r".*?" + _AIRPORT, re.DOTALL)
    fn_re = re.compile(r"(LH\s*\d{3,5})")

    dta_matches = list(dta_re.finditer(text))
    fn_matches = list(fn_re.finditer(text))

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

        # Find the flight number that falls between the two date/time matches
        flight_number = ""
        for fn_m in fn_matches:
            if dep_m.start() <= fn_m.start() <= arr_m.start():
                flight_number = fn_m.group(1).replace(" ", "")
                break

        flight = _make_flight_dict(
            rule, flight_number,
            dep_m.group(3), arr_m.group(3),
            dep_dt, arr_dt,
            booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights
