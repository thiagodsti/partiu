"""
Pegasus Airlines (PC) booking-confirmation parser.

Pegasus mails its own branded "Rezervasyonun onaylandı!" confirmation with no
attachment at all — there is no GDS receipt behind it — so the itinerary exists
only as this HTML table, one block per leg.  As ``html_to_text`` renders it::

    Gidiş Uçuş Bilgileri            ← "outbound" (or "Dönüş" = return)
    Stockholm - Arlanda (ARN)       ← route header, one endpoint per line
    Istanbul Sabiha Gökçen (SAW)
    19 Eylül 2026                   ← travel date
    PC1284                          ← flight number
    ARN                             ← departure IATA
    3sa 35dk                        ← duration, may be absent
    SAW                             ← arrival IATA
    Stockholm - Isveç               ← departure city - country
    02:45                           ← departure time
    5                               ← departure terminal, may be absent
    Istanbul - Türkiye              ← arrival city - country
    07:20                           ← arrival time
    MAIN                            ← arrival terminal, may be absent

The block is walked line by line rather than matched by one regex because the
duration and both terminal lines are independently optional, and a regex with
three optional filler lines in it drifts onto the *next* leg's values as soon as
one of them is missing.  Walking forward with a hard stop at the next flight
number keeps every value inside its own leg.

The date is never repeated inside the block, so it is taken from the nearest
bare-date line *above* it.  "Nearest line containing a date" would instead reach
``Check-in Açılış: 12 Eylül 2026 02:45`` at the top of the mail and file the
outbound leg on the check-in opening day.
"""

import logging
import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    get_email_text,
    make_flight_dict,
    normalize_fn,
)

logger = logging.getLogger(__name__)

# "PC1284" on a line of its own — the block anchor. Pegasus never codeshares in
# this template, so the carrier code is pinned rather than left as [A-Z]{2}:
# "MAIN" and "TESTPC"-shaped tokens elsewhere in the mail cannot be mistaken for
# an anchor, and a codeshare marketing number would belong to the other airline.
_FLIGHT_NO_LINE_RE = re.compile(r"^(PC[ \xa0]?\d{2,4})$")
_IATA_LINE_RE = re.compile(r"^[A-Z]{3}$")
_TIME_LINE_RE = re.compile(r"^(\d{1,2}:\d{2})$")
# "5", "T2", "MAIN", "INTL" — the line directly under a time, when present.
# Uppercase-and-digits only, so a "Stockholm - Isveç" city line never qualifies.
_TERMINAL_LINE_RE = re.compile(r"^(T?\d{1,2}[A-Z]?|[A-Z]{1,6}\d{0,2})$")
# A line that is nothing but a date: "19 Eylül 2026", optionally + weekday.
_DATE_ONLY_LINE_RE = re.compile(r"^(\d{1,2}\s+[^\W\d_]{3,12}\.?\s+\d{4})(?:\s+[^\W\d_]+)?$")

# How far below the flight number the rest of a leg may sit, and how far above it
# the date may sit. A return leg's block starts a fresh header, so both are small.
_BLOCK_LINES = 14
_LOOKBACK = 8

# "Sevgili Bob Traveler," — the greeting names the booking holder. Read here
# rather than left to the shared extractor, which recognises none of these
# Turkish salutations and captures only a first name from the ones it does know.
# The passenger list under "Yolcu Bilgileri" is not used instead: it repeats for
# every leg and names co-travellers the flight dict has no room for.
_GREETING_RE = re.compile(
    r"^(?:Sevgili|De[ğg]erli|Say[ıi]n|Dear)\s+"
    r"([^\W\d_][^\W\d_]*(?:[ \t]+[^\W\d_][^\W\d_]*)+)\s*,$",
    re.MULTILINE,
)


def _header_date(lines: list[str], idx: int):
    """Date from the nearest bare-date line above line *idx*."""
    for line in reversed(lines[max(0, idx - _LOOKBACK) : idx]):
        m = _DATE_ONLY_LINE_RE.match(line)
        if m and (parsed := parse_flight_date(m.group(1))):
            return parsed
    return None


def _read_block(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Collect the IATA codes, times and terminals of one leg block.

    A terminal is only recorded for the line directly under a time, so the two
    lists stay index-aligned with *times* (an empty string where the mail printed
    no terminal).
    """
    iatas: list[str] = []
    times: list[str] = []
    terminals: list[str] = []
    for i, line in enumerate(lines):
        if _IATA_LINE_RE.match(line) and len(iatas) < 2:
            iatas.append(line)
        elif (m := _TIME_LINE_RE.match(line)) and len(times) < 2:
            times.append(m.group(1))
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            terminals.append(nxt if _TERMINAL_LINE_RE.match(nxt) else "")
        if len(iatas) == 2 and len(times) == 2:
            break
    return iatas, times, terminals


def _extract_legs(text: str, rule) -> list[dict]:
    """Walk the mail's leg blocks, one per flight-number line."""
    lines = text.split("\n")
    anchors = [i for i, line in enumerate(lines) if _FLIGHT_NO_LINE_RE.match(line)]

    flights = []
    for pos, idx in enumerate(anchors):
        # Stop at the next leg's anchor so a truncated block borrows nothing.
        end = min(
            idx + 1 + _BLOCK_LINES, anchors[pos + 1] if pos + 1 < len(anchors) else len(lines)
        )
        iatas, times, terminals = _read_block(lines[idx + 1 : end])
        if len(iatas) < 2 or len(times) < 2:
            logger.debug("Pegasus: incomplete block for %s at line %d", lines[idx], idx)
            continue

        dep_date = _header_date(lines, idx)
        if not dep_date:
            logger.debug("Pegasus: no header date above %s at line %d", lines[idx], idx)
            continue

        dep_dt = _build_datetime(dep_date, times[0])
        arr_dt = _build_datetime(dep_date, times[1])
        if dep_dt and arr_dt:
            arr_dt = fix_overnight(dep_dt, arr_dt)

        flight = make_flight_dict(
            rule, normalize_fn(lines[idx]), iatas[0], iatas[1], dep_dt, arr_dt
        )
        if flight:
            flight["departure_terminal"] = terminals[0]
            flight["arrival_terminal"] = terminals[1]
            flights.append(flight)
    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Pegasus booking-confirmation email."""
    text = get_email_text(email_msg)
    flights = _extract_legs(text, rule)

    greeting = _GREETING_RE.search(text)
    if greeting:
        for flight in flights:
            flight["passenger_name"] = greeting.group(1).strip()

    return enrich_flights(flights, text, email_msg.subject)
