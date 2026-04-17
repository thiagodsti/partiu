"""
Qatar Airways (QR) flight extractor.

Handles the Qatar Airways booking confirmation email format:
  Tue, 14 Dec 2021
  15:30
  ARN
  Stockholm,Arlanda Airport
  Sweden
  6h 10 m
  Tue, 14 Dec 2021
  23:40
  DOH
  Doha,Hamad International Airport
  Qatar
  QR 168

The IATA codes appear directly in the stripped HTML text.
"""

import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    get_email_text,
    make_flight_dict,
    normalize_fn,
)

# Per-flight-leg pattern in stripped HTML (newline-separated)
_leg_re = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+)?"
    r"(\d{1,2}\s+\w{3}\s+\d{4})\n"  # g1: dep date "14 Dec 2021"
    r"(\d{2}:\d{2})\n"  # g2: dep time
    r"([A-Z]{3})\n"  # g3: dep IATA
    r"[^\n]+\n"  # city name
    r"[^\n]+\n"  # country
    r"(?:Terminal\s*:[^\n]+\n)?"  # optional terminal
    r"[\dhm ]+\n"  # duration "6h 10 m"
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+)?"
    r"(\d{1,2}\s+\w{3}\s+\d{4})\n"  # g4: arr date
    r"(\d{2}:\d{2})\n"  # g5: arr time
    r"([A-Z]{3})\n"  # g6: arr IATA
    r"[^\n]+\n"  # city name
    r"[^\n]+\n"  # country
    r"(?:Terminal\s*:[^\n]+\n)?"  # optional terminal
    r"(QR[\s\xa0]*\d{2,4})\b",  # g7: flight number
)


def _extract_legs(text: str, rule) -> list[dict]:
    """Parse all flight legs from the newline-separated body text."""
    flights = []
    for m in _leg_re.finditer(text):
        dep_date = parse_flight_date(m.group(1))
        arr_date = parse_flight_date(m.group(4))
        if not dep_date or not arr_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(2))
        arr_dt = _build_datetime(arr_date, m.group(5))
        if not dep_dt or not arr_dt:
            continue
        flight = make_flight_dict(
            rule,
            normalize_fn(m.group(7)),
            m.group(3),
            m.group(6),
            dep_dt,
            arr_dt,
        )
        if flight:
            flights.append(flight)
    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Qatar Airways booking confirmation email."""
    text = get_email_text(email_msg)
    flights = _extract_legs(text, rule)
    return enrich_flights(flights, text, email_msg.subject)
