"""
Vueling (VY) flight extractor.

Parses the "Your booking confirmation" email. Each direction is introduced by an
"Outbound" / "Return" heading, then printed one field per line with the two
endpoints stacked rather than paired:

    Outbound
    Basic
    Wednesday, 27 April 2022
    Stockholm (T2)        ← city + terminal, no IATA code
    Barcelona (T1)
    ARN                   ← the codes come *after* both city lines
    BCN
    11:35h
    15:20h
    VY1266

Reading this pairwise from the top would mate Stockholm with Barcelona's
terminal, so the block is classified by *kind* — codes, times, flight number —
and the first of each kind is the departure, the second the arrival.
"""

import logging
import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    get_email_text_newline,
    make_flight_dict,
    normalize_fn,
)

logger = logging.getLogger(__name__)

_direction_heading_re = re.compile(r"^(?:Outbound|Return|Ida|Vuelta|Anada|Tornada)$", re.IGNORECASE)
_iata_re = re.compile(r"^([A-Z]{3})$")
# "11:35h" — Vueling suffixes its times with a bare "h".
_time_re = re.compile(r"^(\d{1,2}:\d{2})[\s\xa0]*h?$", re.IGNORECASE)
_flight_re = re.compile(r"^(VY[\s\xa0]*\d{3,4})$")


def _extract_booking_confirmation(text: str, rule) -> list[dict]:
    """Read the per-direction booking-confirmation blocks described above."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    starts = [i for i, ln in enumerate(lines) if _direction_heading_re.match(ln)]
    if not starts:
        return []

    flights: list[dict] = []
    seen: set[str] = set()
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block = lines[start + 1 : end]

        flight_date = None
        codes: list[str] = []
        times: list[str] = []
        fn = ""
        for ln in block:
            if flight_date is None:
                d = parse_flight_date(ln)
                if d is not None:
                    flight_date = d
                    continue
            m = _flight_re.match(ln)
            if m:
                fn = normalize_fn(m.group(1))
                continue
            m = _iata_re.match(ln)
            if m:
                codes.append(m.group(1))
                continue
            m = _time_re.match(ln)
            if m:
                times.append(m.group(1))

        if flight_date is None or not fn or len(codes) < 2 or len(times) < 2:
            continue
        if codes[0] == codes[1] or fn in seen:
            continue

        dep_dt = _build_datetime(flight_date, times[0])
        arr_dt = _build_datetime(flight_date, times[1])
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)

        flight = make_flight_dict(rule, fn, codes[0], codes[1], dep_dt, arr_dt)
        if flight:
            seen.add(fn)
            flights.append(flight)

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Vueling email."""
    text = get_email_text_newline(email_msg)
    flights = _extract_booking_confirmation(text, rule)
    return enrich_flights(flights, text, email_msg.subject) if flights else []
