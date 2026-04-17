"""
Austrian Airlines (OS) flight extractor.

Three email formats are supported:

1. Boarding-pass email (no-reply@austrian.com):
   Contains compact date (03APR24), flight number (OS 317), city names
   (Vienna, Stockholm Arlanda), and two HH:MM times.

2. Travel confirmation (subject "travel" or "confirm"):
   Contains date, city names, flight number + "0 PC", and times.

3. Check-in email (subject contains "check-in"):
   IATA codes VIE / ARN appear directly with OS317.

Cancellation emails (subject contains "cancellation") → return [].
"""

import logging
import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _get_text,
    enrich_flights,
    make_flight_dict,
    normalize_fn,
    resolve_iata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Boarding-pass format
# ---------------------------------------------------------------------------
_boarding_pass_date_re = re.compile(r"\b(\d{2}[A-Z]{3}\d{2})\b")
_boarding_pass_flight_number_re = re.compile(r"\b(OS\s*\d{3,4})\b")
_time_re = re.compile(r"\b(\d{2}:\d{2})\b")
_seat_re = re.compile(r"\bSeat\s*\n\s*(\w+)", re.IGNORECASE)


def _extract_boarding_pass(text: str, rule) -> list[dict]:
    """Try to extract from boarding-pass plain-text format."""
    date_m = _boarding_pass_date_re.search(text)
    fn_m = _boarding_pass_flight_number_re.search(text)
    if not date_m or not fn_m:
        return []

    base_dt = parse_flight_date(date_m.group(1))
    if not base_dt:
        return []

    flight_number = normalize_fn(fn_m.group(1))

    # After the flight number, look for city names and times
    after_fn = text[fn_m.end() : fn_m.end() + 400]
    lines = [line.strip() for line in after_fn.split("\n") if line.strip()]

    city_lines = []
    time_lines = []
    for line in lines:
        if re.match(r"^\d{2}:\d{2}$", line):
            time_lines.append(line)
        elif re.match(r"^[A-Za-z][A-Za-z\s]+$", line) and len(line) > 3:
            if not re.search(
                r"\b(Terminal|Boarding|Gate|closes|Sec|Baggage|Area|Place|Time|Servus)\b",
                line,
                re.IGNORECASE,
            ):
                # Skip lines that look like passenger names (all-uppercase words)
                if not re.match(r"^(?:[A-Z]+\s+)+[A-Z]+$", line):
                    city_lines.append(line)
        if len(time_lines) == 2:
            break

    if len(city_lines) < 2 or len(time_lines) < 2:
        return []

    # Resolve city names to IATA codes
    dep_iata = (
        city_lines[0] if re.match(r"^[A-Z]{3}$", city_lines[0]) else resolve_iata(city_lines[0])
    )
    arr_iata = (
        city_lines[1] if re.match(r"^[A-Z]{3}$", city_lines[1]) else resolve_iata(city_lines[1])
    )
    if not dep_iata or not arr_iata:
        logger.debug(
            "Austrian boarding-pass: could not resolve IATA for %r / %r",
            city_lines[0],
            city_lines[1],
        )
        return []

    flight = make_flight_dict(
        rule,
        flight_number,
        dep_iata,
        arr_iata,
        _build_datetime(base_dt, time_lines[0]),
        _build_datetime(base_dt, time_lines[1]),
    )
    if not flight:
        return []

    # Seat
    seat_m = _seat_re.search(text)
    if seat_m:
        flight["seat"] = seat_m.group(1)

    return enrich_flights([flight], text)


# ---------------------------------------------------------------------------
# Travel confirmation / check-in format
# ---------------------------------------------------------------------------
_checkin_re = re.compile(
    r"\b(?P<dep>[A-Z]{3})\b\s+\b(?P<arr>[A-Z]{3})\b"
    r"[\s\S]{0,200}?"
    r"\b(?P<fn>OS\s*\d{3,4})\b",
)
_confirmation_date_re = re.compile(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4})")
_confirmation_line_re = re.compile(
    r"(OS\s*\d{3,4})\s+\d+\s+PC\s*\n"
    r"(\d{2}:\d{2})\s+(\d{2}:\d{2})",
)


def _extract_confirmation(text: str, rule) -> list[dict]:
    """Try to extract from travel confirmation or check-in email format."""
    # Check-in format (IATA codes present directly)
    m = _checkin_re.search(text)
    if m:
        fn = normalize_fn(m.group("fn"))
        dep_iata, arr_iata = m.group("dep"), m.group("arr")

        fn_pos = m.end()
        times = _time_re.findall(text[fn_pos : fn_pos + 200])
        if len(times) < 2:
            times = _time_re.findall(text[: fn_pos + 200])

        date_m = _confirmation_date_re.search(text)
        if not date_m:
            return []
        base_dt = parse_flight_date(date_m.group(1))
        if not base_dt:
            base_dt = parse_flight_date(date_m.group(1).replace(" ", ""))
        if not base_dt:
            return []

        all_times = _time_re.findall(text)
        if len(all_times) < 2:
            return []

        flight = make_flight_dict(
            rule,
            fn,
            dep_iata,
            arr_iata,
            _build_datetime(base_dt, all_times[0]),
            _build_datetime(base_dt, all_times[1]),
        )
        return enrich_flights([flight], text) if flight else []

    # Travel confirmation format
    confirm_m = _confirmation_line_re.search(text)
    if confirm_m:
        fn = normalize_fn(confirm_m.group(1))
        dep_time, arr_time = confirm_m.group(2), confirm_m.group(3)

        date_m = _confirmation_date_re.search(text)
        if not date_m:
            return []
        base_dt = parse_flight_date(date_m.group(1))
        if not base_dt:
            return []

        # Find city names before the flight line
        conf_pos = confirm_m.start()
        before_fn = text[max(0, conf_pos - 300) : conf_pos]
        city_words = re.findall(
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Economy|Business|First)",
            before_fn,
        )
        dep_city = arr_city = ""
        if len(city_words) >= 2:
            dep_city, arr_city = city_words[-2], city_words[-1]
        elif len(city_words) == 1:
            segs = re.findall(r"([A-Za-z ]+?)\s+(?:Intl|Airport|International)", before_fn)
            if segs:
                dep_city = segs[0]

        dep_iata = resolve_iata(dep_city) if dep_city else ""
        arr_iata = resolve_iata(arr_city) if arr_city else ""
        if not dep_iata or not arr_iata:
            return []

        flight = make_flight_dict(
            rule,
            fn,
            dep_iata,
            arr_iata,
            _build_datetime(base_dt, dep_time),
            _build_datetime(base_dt, arr_time),
        )
        return enrich_flights([flight], text) if flight else []

    return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from an Austrian Airlines email."""
    subject = (email_msg.subject or "").lower()

    # Skip cancellation emails
    if "cancellation" in subject:
        return []

    body = email_msg.body or ""

    # Try boarding-pass format (plain text, then HTML)
    flights = _extract_boarding_pass(body, rule)
    if flights:
        return flights

    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _extract_boarding_pass(html_text, rule)
        if flights:
            return flights

    # Try confirmation/check-in format (plain text, then HTML)
    flights = _extract_confirmation(body, rule)
    if flights:
        return flights

    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _extract_confirmation(html_text, rule)
        if flights:
            return flights

    return []
