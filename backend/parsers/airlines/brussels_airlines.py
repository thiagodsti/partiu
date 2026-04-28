"""
Brussels Airlines (SN) flight extractor.

Parses the structured e-ticket body embedded in booking confirmation emails
from brusselsairlines.com.  The email body contains a multi-page "PASSENGER
DOCUMENT" section that repeats two-column flight blocks such as::

    FLIGHT 1 FLIGHT 2
    Flight Flight
    SN2298 SN3107
    From From
    Stockholm (ARN) Brussels (BRU)
    ...
    Departure date Departure time Terminal Departure date Departure time
    03 July 2026 06:30 5 03 July 2026 10:50
    Arrival date Arrival time Arrival date Arrival time
    03 July 2026 08:45 03 July 2026 13:00
    Travel class Status Travel class Status
    Economy Light (S) Confirmed Economy Light (S) Confirmed

Each block may contain 1 or 2 flights (side-by-side columns).  Multiple
blocks are stacked vertically for round trips.
"""

import logging
import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    extract_booking_reference,
    extract_passenger,
    fix_overnight,
    make_flight_dict,
    normalize_fn,
)

logger = logging.getLogger(__name__)

# Matches a "FLIGHT X" or "FLIGHT X FLIGHT Y" block header line
_BLOCK_HEADER_RE = re.compile(r"^(FLIGHT\s+\d+(?:\s+FLIGHT\s+\d+)*)$")

# Flight number pattern for Brussels Airlines (SN prefix)
_FLIGHT_NUM_RE = re.compile(r"\b(SN\s*\d{3,5})\b")

# IATA code inside parentheses: "(ARN)"
_IATA_RE = re.compile(r"\(([A-Z]{3})\)")

# Date + time pair: "03 July 2026 06:30" — possibly followed by a terminal token
_DATE_TIME_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+(\d{2}:\d{2})")

# Cabin class extraction: "Economy Light (S) Confirmed" or "Business Confirmed"
_CABIN_CLASS_RE = re.compile(r"(Economy\s+\w+(?:\s+\(\w+\))?|Business(?:\s+\w+)?|First(?:\s+\w+)?)")


def _parse_flight_block(lines: list[str], start: int) -> tuple[list[dict], int]:
    """
    Parse one FLIGHT X [FLIGHT Y] block starting at *start*.

    Returns ``(flights, next_i)`` where *next_i* is the index after the block.
    The block scan stops when a new ``FLIGHT`` header or ``PASSENGER DOCUMENT``
    line is encountered, or after 25 lines.
    """

    fns: list[str] = []
    dep_iatas: list[str] = []
    arr_iatas: list[str] = []
    dep_datetimes = []
    arr_datetimes = []
    cabin_classes: list[str] = []

    state = "seek_fns"
    i = start + 1
    end = min(start + 30, len(lines))

    while i < end:
        line = lines[i]

        # Stop at a new block
        if _BLOCK_HEADER_RE.match(line) or line == "PASSENGER DOCUMENT":
            break

        if state == "seek_fns":
            fn_matches = _FLIGHT_NUM_RE.findall(line)
            if fn_matches:
                fns = [normalize_fn(fn) for fn in fn_matches]
                state = "seek_dep"

        elif state == "seek_dep":
            # Skip "From From" header lines
            if re.match(r"^From\b", line, re.IGNORECASE) and len(line) < 15:
                i += 1
                continue
            # Next line after "From" with parenthesised IATA codes
            codes = _IATA_RE.findall(line)
            if codes and len(codes) >= 1:
                dep_iatas = codes
                state = "seek_arr"

        elif state == "seek_arr":
            # Skip "to to" header lines
            if re.match(r"^to\b", line, re.IGNORECASE) and len(line) < 10:
                i += 1
                continue
            codes = _IATA_RE.findall(line)
            if codes and len(codes) >= 1:
                arr_iatas = codes
                state = "seek_dep_dt"

        elif state == "seek_dep_dt":
            if re.search(r"Departure date", line, re.IGNORECASE):
                # Next non-empty line has the actual date+time values
                i += 1
                while i < end and not lines[i].strip():
                    i += 1
                if i < end:
                    pairs = _DATE_TIME_RE.findall(lines[i])
                    for date_str, time_str in pairs:
                        d = parse_flight_date(date_str)
                        if d:
                            dt = _build_datetime(d, time_str)
                            if dt:
                                dep_datetimes.append(dt)
                state = "seek_arr_dt"

        elif state == "seek_arr_dt":
            if re.search(r"Arrival date", line, re.IGNORECASE):
                i += 1
                while i < end and not lines[i].strip():
                    i += 1
                if i < end:
                    pairs = _DATE_TIME_RE.findall(lines[i])
                    for date_str, time_str in pairs:
                        d = parse_flight_date(date_str)
                        if d:
                            dt = _build_datetime(d, time_str)
                            if dt:
                                arr_datetimes.append(dt)
                state = "seek_class"

        elif state == "seek_class":
            if re.search(r"Travel class", line, re.IGNORECASE):
                i += 1
                while i < end and not lines[i].strip():
                    i += 1
                if i < end:
                    cabin_classes = _CABIN_CLASS_RE.findall(lines[i])
            # Block is complete whether or not we found the class
            break

        i += 1

    return _build_flights(fns, dep_iatas, arr_iatas, dep_datetimes, arr_datetimes, cabin_classes), i


def _build_flights(
    fns: list[str],
    dep_iatas: list[str],
    arr_iatas: list[str],
    dep_datetimes: list,
    arr_datetimes: list,
    cabin_classes: list[str],
) -> list[dict]:
    """Assemble flight dicts from the per-column lists extracted from one block."""
    flights: list[dict] = []
    for idx, fn in enumerate(fns):
        dep_iata = dep_iatas[idx] if idx < len(dep_iatas) else ""
        arr_iata = arr_iatas[idx] if idx < len(arr_iatas) else ""
        dep_dt = dep_datetimes[idx] if idx < len(dep_datetimes) else None
        arr_dt = arr_datetimes[idx] if idx < len(arr_datetimes) else None
        cabin = cabin_classes[idx] if idx < len(cabin_classes) else ""

        if not dep_iata or not arr_iata or dep_dt is None or arr_dt is None:
            logger.debug("Brussels Airlines: incomplete data for %s, skip", fn)
            continue
        if dep_iata == arr_iata:
            continue

        arr_dt = fix_overnight(dep_dt, arr_dt)
        flights.append(
            {
                "_fn": fn,
                "_dep": dep_iata,
                "_arr": arr_iata,
                "_dep_dt": dep_dt,
                "_arr_dt": arr_dt,
                "_cabin": cabin,
            }
        )
    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Brussels Airlines booking confirmation email.

    The structured e-ticket data lives in PDF attachments (e-ticket_*.pdf),
    not in the HTML body.  We extract text from those PDFs first, then fall
    back to the pre-converted plain-text body (which also includes PDF text
    when the email was loaded via the full pipeline).
    """
    # Prefer PDF text — contains the structured PASSENGER DOCUMENT / FLIGHT blocks
    body = ""
    if email_msg.pdf_attachments:
        body = email_msg.get_pdf_text()

    # Fallback: plain-text body (already includes PDF text when using the full pipeline)
    if not body:
        body = email_msg.body or ""

    if not body:
        return []

    subject = email_msg.subject or ""
    booking_ref = extract_booking_reference(body, subject)
    passenger = extract_passenger(body)

    lines = [ln.strip() for ln in body.split("\n")]

    raw_flights: list[dict] = []
    seen_keys: set[tuple] = set()
    i = 0

    while i < len(lines):
        m = _BLOCK_HEADER_RE.match(lines[i])
        if m:
            block_flights, i = _parse_flight_block(lines, i)
            for bf in block_flights:
                key = (bf["_fn"], bf["_dep"], bf["_arr"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    raw_flights.append(bf)
        else:
            i += 1

    flights: list[dict] = []
    for bf in raw_flights:
        flight = make_flight_dict(
            rule,
            bf["_fn"],
            bf["_dep"],
            bf["_arr"],
            bf["_dep_dt"],
            bf["_arr_dt"],
            booking_ref,
            passenger,
        )
        if flight:
            flight["cabin_class"] = bf["_cabin"]
            flights.append(flight)

    if flights:
        logger.info(
            "Brussels Airlines: extracted %d flight(s) from '%s'",
            len(flights),
            subject[:60],
        )
    return flights
