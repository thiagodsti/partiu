"""
British Airways flight extractor.

BA e-ticket emails have a clean plain-text itinerary section:

  BA0781: British Airways | Euro Traveller | Confirmed
  ----------------------------------------------------
  Depart: 23 Dec 2024 17:55 - Arlanda (Stockholm) - Terminal 2
  Arrive: 23 Dec 2024 19:40 - Heathrow (London) - Terminal 5

Airport names (not IATA codes) are resolved against the airports DB.
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
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Pattern for one flight leg in the plain-text body
_leg_re = re.compile(
    r"(?P<fn>[A-Z]{2}\d{3,5}):\s+[^\n]+\|\s*Confirmed\s*\n"
    r"[-]+\s*\n"
    r"Depart:\s+(?P<dep_date>\d{1,2}\s+\w+\s+\d{4})\s+(?P<dep_time>\d{2}:\d{2})"
    r"\s+-\s+(?P<dep_name>[^-\n]+?)\s+-\s+Terminal\s+[^\n]+\n"
    r"Arrive:\s+(?P<arr_date>\d{1,2}\s+\w+\s+\d{4})\s+(?P<arr_time>\d{2}:\d{2})"
    r"\s+-\s+(?P<arr_name>[^-\n]+?)\s+-\s+Terminal",
    re.IGNORECASE,
)


def _extract_legs(body: str, rule) -> list[dict]:
    """Parse all flight legs from the plain-text body."""
    flights = []
    for m in _leg_re.finditer(body):
        dep_date = parse_flight_date(m.group("dep_date"))
        arr_date = parse_flight_date(m.group("arr_date"))
        if not dep_date or not arr_date:
            continue

        dep_iata = resolve_iata(m.group("dep_name").strip())
        arr_iata = resolve_iata(m.group("arr_name").strip())
        if not dep_iata or not arr_iata:
            logger.debug(
                "BA: could not resolve IATA for %r / %r",
                m.group("dep_name"),
                m.group("arr_name"),
            )
            continue

        flight = make_flight_dict(
            rule,
            m.group("fn").replace(" ", ""),
            dep_iata,
            arr_iata,
            _build_datetime(dep_date, m.group("dep_time")),
            _build_datetime(arr_date, m.group("arr_time")),
        )
        if flight:
            flights.append(flight)

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a British Airways e-ticket email."""
    body = email_msg.body or ""

    # Fall back to stripping HTML if plain text is CSS-heavy
    if email_msg.html_body and len(body) < 200:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        body = _get_text(soup)

    flights = _extract_legs(body, rule)
    return enrich_flights(flights, body, email_msg.subject)
