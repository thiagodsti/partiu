"""
Austrian Airlines (OS) flight extractor.

Three email formats are supported:

1. Boarding-pass email (no-reply@austrian.com, "Boarding pass for your flight"):
   Plain text contains:
     03APR24         ← date (DDMMMYY, no spaces)
     OS 317          ← flight number (may have space)
     Vienna          ← dep city name (ignored — IATA follows below)
     Stockholm Arlanda
     20:25
     22:35
     ...
     Booking code
     RHFNEJ          ← booking ref
     Seat
     23F             ← seat

   But the IATA codes (VIE/ARN) also appear near the date/flight block:
     03APR24
     OS 317
     TEST PASSENGER  ← passenger name (between flight# and city)
     Vienna
     Stockholm Arlanda
     20:25
     22:35

   Actually the fixture shows VIE/ARN do NOT appear directly in the boarding-pass
   plain text — the city names "Vienna" and "Stockholm Arlanda" are present.
   We use resolve_iata() to convert them.

2. Travel confirmation (plain text, subject "travel" or "confirm"):
   Booking Code RHFNEJ
   03 Apr 24, ... Vienna Intl Stockholm Economy Light,
   OS317 0 PC
   20:25 22:35 Terminal 3 Terminal 5 confirmed

3. Check-in email (subject contains "check-in"):
   IATA codes VIE / ARN appear directly.
   OS317 appears directly.

Cancellation emails (subject contains "cancellation") → return [].
"""

import logging
import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _extract_booking_ref_text,
    _get_text,
    _make_flight_dict,
    normalize_fn,
    resolve_iata,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Boarding-pass format
# ---------------------------------------------------------------------------
# Pattern: DDMMMYY\nOS NNN\n...\nCity name\nCity name\nHH:MM\nHH:MM
_BP_DATE_RE = re.compile(r"\b(\d{2}[A-Z]{3}\d{2})\b")
_BP_FN_RE = re.compile(r"\b(OS\s*\d{3,4})\b")
_TIME_RE = re.compile(r"\b(\d{2}:\d{2})\b")
_SEAT_RE = re.compile(r"\bSeat\s*\n\s*(\w+)", re.IGNORECASE)


def _extract_boarding_pass(text: str, rule) -> list[dict]:
    """Try to extract from boarding-pass plain-text format."""
    date_m = _BP_DATE_RE.search(text)
    fn_m = _BP_FN_RE.search(text)
    if not date_m or not fn_m:
        return []

    base_dt = parse_flight_date(date_m.group(1))
    if not base_dt:
        return []

    flight_number = normalize_fn(fn_m.group(1))

    # After the flight number, look for two city names followed by two times
    # The block looks like: \nOS 317\nPASSENGER\nVienna\nStockholm Arlanda\n20:25\n22:35
    fn_pos = fn_m.end()
    after_fn = text[fn_pos : fn_pos + 400]

    # Find city lines: lines that look like city names (not times, not seat info, etc.)
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

    # We need at least 2 city names and 2 times
    dep_city = arr_city = ""
    if len(city_lines) >= 2:
        dep_city = city_lines[0]
        arr_city = city_lines[1]

    dep_iata = arr_iata = ""
    # Try direct 3-letter code match first (check-in format)
    if re.match(r"^[A-Z]{3}$", dep_city):
        dep_iata = dep_city
    else:
        dep_iata = resolve_iata(dep_city)

    if re.match(r"^[A-Z]{3}$", arr_city):
        arr_iata = arr_city
    else:
        arr_iata = resolve_iata(arr_city)

    if not dep_iata or not arr_iata:
        logger.debug(
            "Austrian boarding-pass: could not resolve IATA for %r / %r", dep_city, arr_city
        )
        return []

    if len(time_lines) < 2:
        logger.debug("Austrian boarding-pass: found only %d time values", len(time_lines))
        return []

    dep_dt = _build_datetime(base_dt, time_lines[0])
    arr_dt = _build_datetime(base_dt, time_lines[1])
    if not dep_dt or not arr_dt:
        return []

    # Booking reference
    booking_ref = _extract_booking_ref_text(text)

    # Seat
    seat_m = _SEAT_RE.search(text)
    seat = seat_m.group(1) if seat_m else ""

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
    if flight and seat:
        flight["seat"] = seat
    return [flight] if flight else []


# ---------------------------------------------------------------------------
# Travel confirmation / check-in format
# ---------------------------------------------------------------------------
# Check-in format has IATA codes directly:
#   VIE\nARN\nOS317\n...
_CHECKIN_RE = re.compile(
    r"\b(?P<dep>[A-Z]{3})\b\s+\b(?P<arr>[A-Z]{3})\b"
    r"[\s\S]{0,200}?"
    r"\b(?P<fn>OS\s*\d{3,4})\b",
)

# Travel confirmation format:
#   "03 Apr 24, ... Vienna Intl Stockholm Economy Light,\nOS317 0 PC\n20:25 22:35 Terminal..."
_CONFIRM_DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4})")
_CONFIRM_LINE_RE = re.compile(
    r"(OS\s*\d{3,4})\s+\d+\s+PC\s*\n"
    r"(\d{2}:\d{2})\s+(\d{2}:\d{2})",
)


def _extract_confirmation(text: str, rule) -> list[dict]:
    """Try to extract from travel confirmation or check-in email format."""
    # First try check-in format (IATA codes present)
    m = _CHECKIN_RE.search(text)
    if m:
        fn = normalize_fn(m.group("fn"))
        dep_iata = m.group("dep")
        arr_iata = m.group("arr")

        # Find times after flight number
        fn_pos = m.end()
        times = _TIME_RE.findall(text[fn_pos : fn_pos + 200])
        if len(times) < 2:
            times = _TIME_RE.findall(text[: fn_pos + 200])

        # Find date
        date_m = _CONFIRM_DATE_RE.search(text)
        if not date_m:
            return []
        base_dt = parse_flight_date(date_m.group(1))
        if not base_dt:
            base_dt = parse_flight_date(date_m.group(1).replace(" ", ""))
        if not base_dt:
            return []

        # Get times from before/around flight number
        all_times = _TIME_RE.findall(text)
        if len(all_times) < 2:
            return []

        # The first two times near the flight info
        dep_dt = _build_datetime(base_dt, all_times[0])
        arr_dt = _build_datetime(base_dt, all_times[1])
        if not dep_dt or not arr_dt:
            return []

        booking_ref = _extract_booking_ref_text(text)

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
        return [flight] if flight else []

    # Try travel confirmation format
    confirm_m = _CONFIRM_LINE_RE.search(text)
    if confirm_m:
        fn = normalize_fn(confirm_m.group(1))
        dep_time = confirm_m.group(2)
        arr_time = confirm_m.group(3)

        # Find date
        date_m = _CONFIRM_DATE_RE.search(text)
        if not date_m:
            return []
        base_dt = parse_flight_date(date_m.group(1))
        if not base_dt:
            return []

        # Find city names from confirmation text (before OS flight line)
        conf_pos = confirm_m.start()
        before_fn = text[max(0, conf_pos - 300) : conf_pos]
        city_words = re.findall(
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:Economy|Business|First)", before_fn
        )
        dep_city = arr_city = ""
        if len(city_words) >= 2:
            dep_city = city_words[-2]
            arr_city = city_words[-1]
        elif len(city_words) == 1:
            # Try splitting on comma-separated segment
            segs = re.findall(r"([A-Za-z ]+?)\s+(?:Intl|Airport|International)", before_fn)
            if segs:
                dep_city = segs[0]

        dep_iata = resolve_iata(dep_city) if dep_city else ""
        arr_iata = resolve_iata(arr_city) if arr_city else ""

        if not dep_iata or not arr_iata:
            logger.debug(
                "Austrian confirmation: could not resolve IATA for %r / %r", dep_city, arr_city
            )
            return []

        dep_dt = _build_datetime(base_dt, dep_time)
        arr_dt = _build_datetime(base_dt, arr_time)
        if not dep_dt or not arr_dt:
            return []

        booking_ref = _extract_booking_ref_text(text)

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
        return [flight] if flight else []

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

    # Try boarding-pass format first
    flights = _extract_boarding_pass(body, rule)
    if flights:
        logger.debug("Austrian: extracted %d flight(s) (boarding-pass format)", len(flights))
        return flights

    # Try HTML body
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _extract_boarding_pass(html_text, rule)
        if flights:
            logger.debug(
                "Austrian: extracted %d flight(s) from HTML (boarding-pass format)", len(flights)
            )
            return flights

    # Try confirmation/check-in format
    flights = _extract_confirmation(body, rule)
    if flights:
        logger.debug("Austrian: extracted %d flight(s) (confirmation format)", len(flights))
        return flights

    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _extract_confirmation(html_text, rule)
        if flights:
            logger.debug(
                "Austrian: extracted %d flight(s) from HTML (confirmation format)", len(flights)
            )
            return flights

    return []
