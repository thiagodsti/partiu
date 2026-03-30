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
  ...

The IATA codes appear directly in the stripped HTML text.
Booking reference: "Booking reference (PNR) -\n{REF}"
"""

import logging
import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import _build_datetime, _extract_booking_reference, _make_flight_dict, normalize_fn

logger = logging.getLogger(__name__)

# Per-flight-leg pattern in stripped HTML (newline-separated)
_QR_LEG_RE = re.compile(
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


def _extract(text: str, rule, booking_ref: str) -> list[dict]:
    flights = []
    for m in _QR_LEG_RE.finditer(text):
        dep_date = parse_flight_date(m.group(1))
        arr_date = parse_flight_date(m.group(4))
        if not dep_date or not arr_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(2))
        arr_dt = _build_datetime(arr_date, m.group(5))
        if not dep_dt or not arr_dt:
            continue
        fn = normalize_fn(m.group(7))
        flight = _make_flight_dict(rule, fn, m.group(3), m.group(6), dep_dt, arr_dt, booking_ref)
        if flight:
            flights.append(flight)
    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Qatar Airways booking confirmation email."""
    if not email_msg.html_body:
        return []
    soup = BeautifulSoup(email_msg.html_body, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    booking_ref = _extract_booking_reference(soup, email_msg.subject)
    return _extract(text, rule, booking_ref)
