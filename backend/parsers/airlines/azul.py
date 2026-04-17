"""
Azul Brazilian Airlines (AD) flight extractor.

Two email layouts are supported (both produce ``VCP → FLN  AD4849`` style
output — the difference is purely in how date/time and flight number appear):

Layout A — newer format (azul_anonymized.eml):
  VCP
  São Paulo, Viracopos-Campinas     ← optional city name line
  02/03/2026 - 13:20                ← date + time, full year, dash separator
  Voo                               ← flight label on its own line
  4849                              ← flight number on its own line
  FLN
  Florianopolis, Hercilio Luz International
  02/03/2026 - 14:35

Layout B — older format (azul2_anonymized.eml):
  VCP
  02/03 • 13:20                     ← date + time, no year, bullet separator
  Voo 4849                          ← label + number on the same line
  FLN
  02/03 • 14:35

The parser uses the shared ``extract_line_datetime`` and
``extract_line_flight_number`` helpers so that new date/time formats
discovered in any airline's email only need to be added once (in
``shared.py``) to be covered here automatically.
"""

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..shared import (
    _build_datetime,
    _extract_booking_ref_text,
    extract_line_datetime,
    extract_line_flight_number,
    fix_overnight,
)

logger = logging.getLogger(__name__)

_IATA_RE = re.compile(r"^([A-Z]{3})$")


def _extract_flights(text: str, booking_ref: str, rule, ref_year: int | None) -> list[dict]:
    """
    Scan lines for Azul itinerary blocks using shared pattern libraries.

    State machine:
      0  → looking for departure IATA
      1  → found dep IATA, looking for dep datetime (or restart on new IATA)
      2  → found dep datetime, looking for flight number
      3  → found flight number, looking for arrival IATA
      4  → found arr IATA, looking for arr datetime → emit flight, reset to 0
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    flights: list[dict] = []
    state = 0
    dep_iata = arr_iata = flight_number = dep_time_str = ""
    dep_date = None

    for line in lines:
        if state == 0:
            m = _IATA_RE.match(line)
            if m:
                dep_iata = m.group(1)
                state = 1

        elif state == 1:
            # Check for datetime first
            result = extract_line_datetime(line, ref_year)
            if result:
                dep_date, dep_time_str = result
                state = 2
                continue
            # Check for a combined "Voo 4849" line (Layout B can skip state 2)
            fn = extract_line_flight_number(line, rule.airline_code)
            if fn:
                # We have a flight number but no datetime yet — not expected,
                # but guard against stale matches by resetting
                pass
            # Another standalone IATA restarts the departure search
            if _IATA_RE.match(line):
                dep_iata = _IATA_RE.match(line).group(1)  # type: ignore[union-attr]

        elif state == 2:
            fn = extract_line_flight_number(line, rule.airline_code)
            if fn:
                flight_number = fn
                state = 3

        elif state == 3:
            m = _IATA_RE.match(line)
            if m:
                arr_iata = m.group(1)
                state = 4

        elif state == 4:
            result = extract_line_datetime(line, ref_year)
            if result:
                arr_date, arr_time_str = result
                if dep_date and dep_iata != arr_iata:
                    dep_dt = _build_datetime(dep_date, dep_time_str)
                    arr_dt = _build_datetime(arr_date, arr_time_str)
                    if dep_dt and arr_dt:
                        arr_dt = fix_overnight(dep_dt, arr_dt)
                        flights.append(
                            {
                                "airline_name": rule.airline_name,
                                "airline_code": rule.airline_code,
                                "flight_number": flight_number,
                                "departure_airport": dep_iata,
                                "arrival_airport": arr_iata,
                                "departure_datetime": dep_dt,
                                "arrival_datetime": arr_dt,
                                "booking_reference": booking_ref,
                                "passenger_name": "",
                                "seat": "",
                                "cabin_class": "",
                                "departure_terminal": "",
                                "arrival_terminal": "",
                                "departure_gate": "",
                                "arrival_gate": "",
                            }
                        )
                # Reset for next leg
                state = 0
                dep_iata = arr_iata = flight_number = dep_time_str = ""
                dep_date = None

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: parse HTML body, fall back to plain text."""
    subject = email_msg.subject or ""
    ref_year = email_msg.date.year if email_msg.date else datetime.now().year

    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        text = soup.get_text(separator="\n", strip=True)
    else:
        text = email_msg.body or ""

    booking_ref = _extract_booking_ref_text(subject + "\n" + text)
    flights = _extract_flights(text, booking_ref, rule, ref_year)

    if flights:
        logger.debug("Azul: extracted %d flight(s)", len(flights))
    return flights
