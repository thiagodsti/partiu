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

The parser uses a state machine that walks through lines looking for:
  IATA → datetime → flight number → IATA → datetime  (= one flight)

Uses ``extract_line_datetime`` and ``extract_line_flight_number`` from shared
so new date/time formats only need to be added once.
"""

import re

from ..shared import (
    _build_datetime,
    enrich_flights,
    extract_line_datetime,
    extract_line_flight_number,
    fix_overnight,
    get_email_text_newline,
    get_ref_year,
    make_flight_dict,
)

_standalone_iata_re = re.compile(r"^([A-Z]{3})$")


def _extract_flights(text: str, rule, ref_year: int | None) -> list[dict]:
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
            m = _standalone_iata_re.match(line)
            if m:
                dep_iata = m.group(1)
                state = 1

        elif state == 1:
            result = extract_line_datetime(line, ref_year)
            if result:
                dep_date, dep_time_str = result
                state = 2
                continue
            fn = extract_line_flight_number(line, rule.airline_code)
            if fn:
                pass  # flight number without datetime — skip
            if _standalone_iata_re.match(line):
                dep_iata = _standalone_iata_re.match(line).group(1)  # type: ignore[union-attr]

        elif state == 2:
            fn = extract_line_flight_number(line, rule.airline_code)
            if fn:
                flight_number = fn
                state = 3

        elif state == 3:
            m = _standalone_iata_re.match(line)
            if m:
                arr_iata = m.group(1)
                state = 4

        elif state == 4:
            result = extract_line_datetime(line, ref_year)
            if result:
                arr_date, arr_time_str = result
                dep_dt = _build_datetime(dep_date, dep_time_str)
                arr_dt = _build_datetime(arr_date, arr_time_str)
                if dep_dt and arr_dt and dep_iata != arr_iata:
                    arr_dt = fix_overnight(dep_dt, arr_dt)
                    flight = make_flight_dict(
                        rule,
                        flight_number,
                        dep_iata,
                        arr_iata,
                        dep_dt,
                        arr_dt,
                    )
                    if flight:
                        flights.append(flight)
                # Reset for next leg
                state = 0
                dep_iata = arr_iata = flight_number = dep_time_str = ""
                dep_date = None

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from an Azul email (HTML preferred, plain-text fallback)."""
    text = get_email_text_newline(email_msg)
    flights = _extract_flights(text, rule, get_ref_year(email_msg))
    return enrich_flights(flights, text, email_msg.subject)
