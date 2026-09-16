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

4. Booking confirmation ("Thank you for booking with us"): the HTML prints a
   "Booking overview" (date, departure time, flight number, IATA pair) and
   then, per leg, an "Itinerary details" block carrying the arrival time and
   both terminals. Read from the details block, which has everything.

5. Rebooking / "Your Travel Confirmation": a plain-text table whose From and
   To cells are printed as one phrase ("Vienna Intl Stockholm") — see
   _route_from_confirmation_row for how that is split without guessing.

Cancellation emails (subject contains "cancellation") → return [].
"""

import logging
import re

from bs4 import BeautifulSoup

from ..cancellations import leg_cancellation
from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _get_text,
    enrich_flights,
    fix_overnight,
    get_email_text,
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
        dep_iata, arr_iata = _route_from_confirmation_row(before_fn)
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
        if not flight:
            return []
        # "20:25 22:35 Terminal 3 Terminal 5 confirmed" — the terminals trail
        # the times on the same line, departure first.
        terminals = _confirmation_terminals_re.match(text[confirm_m.end() :])
        if terminals:
            flight["departure_terminal"] = terminals.group(1)
            flight["arrival_terminal"] = terminals.group(2)
        name = _confirmation_name_re.search(text)
        if name:
            flight["passenger_name"] = f"{name.group(2).title()} {name.group(1).title()}"
        return enrich_flights([flight], text)

    return []


# The From/To cells of the travel-confirmation table, as one capitalised phrase
# ending at the booking class: "Vienna Intl Stockholm Economy Light".
_confirmation_cities_re = re.compile(
    r"([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*)*)\s+(?:Economy|Business|First|Premium)"
)
# An airport-name suffix marks where the From cell ends and the To cell begins.
_airport_suffix_split_re = re.compile(
    r"^(.*?\b(?:Intl|International|Airport|Apt)\.?)\s+(\S.*)$", re.IGNORECASE
)
_confirmation_terminals_re = re.compile(
    r"\s*Terminal\s+([A-Za-z0-9]{1,3})\s+Terminal\s+([A-Za-z0-9]{1,3})\b"
)
# "Name DOE / JOHN MR" — the ticket's own name line, one per traveller.
_confirmation_name_re = re.compile(
    r"^Name\s+([A-Z][A-Z' -]*?)\s*/\s*([A-Z][A-Z' -]*?)(?:\s+(?:MR|MRS|MS|MSTR|MISS))?\s*$",
    re.MULTILINE,
)


def _route_from_confirmation_row(before_fn: str) -> tuple[str, str]:
    """Resolve the From/To cells that precede a travel-confirmation flight line.

    The table prints both cells in one run of capitalised words, so "Vienna
    Intl Stockholm" is a single phrase and there is nothing structural saying
    where one place ends. Guessing is not an option: split one word early,
    "Intl Stockholm" resolves to Stockholm *Västerås*, a real airport 100 km
    from the one on the ticket. So the split is taken only where the text
    itself marks it — after an airport-name suffix ("Intl", "Airport") — and
    otherwise every split is tried and accepted only when they all agree on
    the same pair. Ambiguity returns nothing, and the leg is dropped visibly.
    """
    phrases = _confirmation_cities_re.findall(before_fn)
    if not phrases:
        return "", ""
    if len(phrases) >= 2:
        return resolve_iata(phrases[-2]), resolve_iata(phrases[-1])

    phrase = phrases[0]
    suffix = _airport_suffix_split_re.match(phrase)
    if suffix:
        return resolve_iata(suffix.group(1)), resolve_iata(suffix.group(2))

    words = phrase.split()
    candidates: set[tuple[str, str]] = set()
    for i in range(1, len(words)):
        dep = resolve_iata(" ".join(words[:i]))
        arr = resolve_iata(" ".join(words[i:]))
        if dep and arr and dep != arr:
            candidates.add((dep, arr))
    if len(candidates) == 1:
        return candidates.pop()
    return "", ""


# ---------------------------------------------------------------------------
# Booking confirmation ("Thank you for booking with us")
# ---------------------------------------------------------------------------
# The HTML renders one field per line. Per leg, the "Itinerary details" block
# reads (after blank lines are collapsed):
#
#     29.03.2024
#     0
#     stop(s)
#     ARN
#     VIE
#     Stockholm
#     Vienna
#     Duration: 2h 15m
#     06:35
#     08:50
#     Itinerary details
#     29.03.2024 - 06:35
#     Stockholm
#     Confirmed
#     Arlanda
#     Terminal 5*
#     29.03.2024 - 08:50
#     Vienna
#     Vienna International Airport
#     Terminal 3*
#     OS318
#
# The "Booking overview" above it prints only the departure time, so it is not
# read — the details block has both times, both terminals and the number.
#
# This has to run *before* _extract_confirmation: its check-in pattern ("two
# IATA codes, then an OS number within 200 chars") matches the overview's
# "ARN / VIE / … / OS317" — the *return* flight number after the *outbound*
# route — and only fails today because no "dd Mon yy" date happens to be in
# the text. A gate on the block's own heading is what keeps that path out.
_booking_confirmation_marker_re = re.compile(r"Itinerary details", re.IGNORECASE)
_booking_leg_re = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\n"
    r"(?:[^\n]*\n){0,4}?"
    r"(?P<dep>[A-Z]{3})\n(?P<arr>[A-Z]{3})\n"
    r"(?:[^\n]*\n){0,4}?"
    r"(?P<dep_time>\d{2}:\d{2})\n(?P<arr_time>\d{2}:\d{2})\n"
    r"(?P<details>(?:[^\n]*\n){0,14}?)"
    r"(?P<fn>OS[ \xa0]*\d{3,4})\n",
    re.MULTILINE,
)
_terminal_line_re = re.compile(r"^Terminal\s*([A-Za-z0-9]{1,3})\*?$", re.MULTILINE)


def _extract_booking_confirmation(text: str, rule) -> list[dict]:
    """Parse the booking confirmation's per-leg "Itinerary details" blocks."""
    if not _booking_confirmation_marker_re.search(text):
        return []
    collapsed = re.sub(r"\n[ \t]*\n+", "\n", text)
    flights = []
    for m in _booking_leg_re.finditer(collapsed):
        dep_date = parse_flight_date(m.group("date"))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group("dep_time"))
        arr_dt = _build_datetime(dep_date, m.group("arr_time"))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flight = make_flight_dict(
            rule, normalize_fn(m.group("fn")), m.group("dep"), m.group("arr"), dep_dt, arr_dt
        )
        if not flight:
            continue
        terminals = _terminal_line_re.findall(m.group("details"))
        if len(terminals) == 2:
            flight["departure_terminal"], flight["arrival_terminal"] = terminals
        flights.append(flight)
    return enrich_flights(flights, text) if flights else []


# ---------------------------------------------------------------------------
# "Travel details" check-in card
# ---------------------------------------------------------------------------
# The check-in reminder prints one column per field, flight number first:
#
#     Travel details
#     03.04.2024
#     OS317
#     VIE          ARN
#     Vienna       Stockholm
#     20:25        22:35
#
# _checkin_re above expects the IATA pair *before* the flight number and a
# "3 Apr 24"-style date, so it matches nothing here.
_travel_details_card_re = re.compile(
    r"^(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4})\n"
    r"(OS[\s\xa0]*\d{3,4})\n"
    r"([A-Z]{3})\n"
    r"([A-Z]{3})\n"
    r"[^\n]+\n"  # departure city
    r"[^\n]+\n"  # arrival city
    r"(\d{1,2}:\d{2})\n"
    r"(\d{1,2}:\d{2})",
    re.MULTILINE,
)


def _extract_travel_details_card(text: str, rule) -> list[dict]:
    """Parse the "Travel details" check-in card layout."""
    flights = []
    for m in _travel_details_card_re.finditer(text):
        dep_date = parse_flight_date(m.group(1))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(5))
        arr_dt = _build_datetime(dep_date, m.group(6))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flight = make_flight_dict(
            rule, normalize_fn(m.group(2)), m.group(3), m.group(4), dep_dt, arr_dt
        )
        if flight:
            flights.append(flight)
    return enrich_flights(flights, text) if flights else []


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

    # Booking confirmation first — see the note above _booking_leg_re for why
    # it must not be reached through _extract_confirmation.
    if email_msg.html_body:
        from ..shared import html_to_text

        flights = _extract_booking_confirmation(html_to_text(email_msg.html_body), rule)
        if flights:
            return flights
    flights = _extract_booking_confirmation(body, rule)
    if flights:
        return flights

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

    # "Travel details" card — needs one field per line, so it reads the
    # newline-separated rendering rather than _get_text's space-joined one.
    if email_msg.html_body:
        from ..shared import html_to_text

        flights = _extract_travel_details_card(html_to_text(email_msg.html_body), rule)
        if flights:
            return flights

    return _extract_travel_details_card(body, rule) if body else []


# ---------------------------------------------------------------------------
# Cancellations
# ---------------------------------------------------------------------------

# "Your Austrian flight OS318 from Stockholm to Vienna on 29.3.2024 has been
# cancelled." — the body sentence. The subject says the same thing in a slightly
# different shape ("Cancellation of your flight OS318 Stockholm - Vienna on
# 29.3.2024"), so both are matched with one pattern that skips whatever sits
# between the flight number and the date.
_os_cancelled_leg_re = re.compile(
    r"\b(OS\s?\d{1,4})\b[^\n]{0,80}?\bon\s+(\d{1,2}\.\d{1,2}\.\d{4})",
    re.IGNORECASE,
)
_os_cancelled_marker_re = re.compile(
    r"cancellation\s+of\s+your\s+flight|has\s+been\s+cancelled|annullierung|storniert",
    re.IGNORECASE,
)


def extract_cancellations(email_msg) -> list[dict]:
    """Austrian cancels one **leg** and names it: flight number and date.

    This is the shape `cancellations.leg_cancellation` exists for, and it must
    not be widened into a booking-level record. The mail carries a booking
    reference too, but OS318 Stockholm→Vienna being cancelled says nothing about
    the return leg held under the same reference — Austrian's own text is
    explicitly about looking for an alternative for *this* flight.

    The date is read through `parse_flight_date` rather than a local strptime,
    for the same reason `sas` filters its block splits through it: that function
    is this package's authority on what a date is, in every language the mail
    arrives in.
    """
    subject = email_msg.subject or ""
    text = get_email_text(email_msg)
    combined = f"{subject}\n{text}"
    if not _os_cancelled_marker_re.search(combined):
        return []

    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw_fn, raw_date in _os_cancelled_leg_re.findall(combined):
        parsed = parse_flight_date(raw_date)
        if not parsed:
            continue
        record = leg_cancellation(normalize_fn(raw_fn), parsed.isoformat())
        # The same sentence appears in the subject and again in the body, so
        # without this the one cancelled leg would be reported twice.
        if record and (key := (record["flight_number"], record["departure_date"])) not in seen:
            seen.add(key)
            records.append(record)
    return records
