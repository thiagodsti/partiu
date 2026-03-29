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
from ..shared import _build_datetime, _get_text, _make_flight_dict

logger = logging.getLogger(__name__)

# Pattern for one flight leg in the plain-text body
_LEG_RE = re.compile(
    r"(?P<fn>[A-Z]{2}\d{3,5}):\s+[^\n]+\|\s*Confirmed\s*\n"
    r"[-]+\s*\n"
    r"Depart:\s+(?P<dep_date>\d{1,2}\s+\w+\s+\d{4})\s+(?P<dep_time>\d{2}:\d{2})"
    r"\s+-\s+(?P<dep_name>[^-\n]+?)\s+-\s+Terminal\s+[^\n]+\n"
    r"Arrive:\s+(?P<arr_date>\d{1,2}\s+\w+\s+\d{4})\s+(?P<arr_time>\d{2}:\d{2})"
    r"\s+-\s+(?P<arr_name>[^-\n]+?)\s+-\s+Terminal",
    re.IGNORECASE,
)

# Booking reference in BA subjects: "Your e-ticket receipt J9CRT8: ..."
_BOOKING_RE = re.compile(
    r"(?:booking\s*(?:ref|reference|code)|receipt|reference|PNR)"
    r"[:\s]+([A-Z0-9]{5,8})",
    re.IGNORECASE,
)

# Passenger list in plain text: "MR THIAGO DINIZDASILVEIRA"
_PASSENGER_RE = re.compile(
    r"Passenger\s+list\s*\n[-]+\s*\n([A-Z][A-Z\s]+)",
)


def _booking_ref(subject: str, body: str) -> str:
    # BA subjects look like: "Your e-ticket receipt J9CRT8: 23 Dec 2024 17:55"
    m = re.search(r"receipt\s+([A-Z0-9]{5,8})[:|\s]", subject, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = _BOOKING_RE.search(subject + "\n" + body)
    return m.group(1).strip() if m else ""


def _passenger(body: str) -> str:
    m = _PASSENGER_RE.search(body)
    if m:
        name = m.group(1).strip().split("\n")[0]
        # Strip salutation prefix
        name = re.sub(r"^(?:MR|MRS|MS|MISS|DR|PROF)\.?\s+", "", name, flags=re.IGNORECASE)
        return name.title()
    return ""


def _resolve_iata(airport_name: str) -> str:
    """Look up IATA code by airport name (text before parenthesis) or city name."""
    # Strip city hint in parens: "Arlanda (Stockholm)" → base="Arlanda", city="Stockholm"
    base = re.sub(r"\s*\(.*?\)", "", airport_name).strip()
    city_m = re.search(r"\(([^)]+)\)", airport_name)
    city_str = city_m.group(1).strip() if city_m else ""

    # Build search terms — try the most specific first
    search_terms = []
    if base:
        search_terms.append(base)
    if city_str:
        search_terms.append(city_str)
    # Also try individual words (handles "Guarulhos Intl" → "Guarulhos")
    for word in base.split():
        if len(word) >= 5 and word not in search_terms:
            search_terms.append(word)

    try:
        from ...database import db_conn

        with db_conn() as conn:
            for term in search_terms:
                # Try airport name
                row = conn.execute(
                    "SELECT iata_code FROM airports WHERE name LIKE ? LIMIT 1",
                    (f"%{term}%",),
                ).fetchone()
                if row:
                    return row["iata_code"]
                # Try city name
                row = conn.execute(
                    "SELECT iata_code FROM airports WHERE city_name LIKE ? LIMIT 1",
                    (f"%{term}%",),
                ).fetchone()
                if row:
                    return row["iata_code"]
    except Exception as e:
        logger.debug("Airport lookup failed for %r: %s", airport_name, e)
    return ""


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a British Airways e-ticket email."""
    body = email_msg.body or ""

    # Fall back to stripping HTML if plain text is CSS-heavy
    if email_msg.html_body and len(body) < 200:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        body = _get_text(soup)

    booking_ref = _booking_ref(email_msg.subject or "", body)
    passenger = _passenger(body)

    flights = []
    for m in _LEG_RE.finditer(body):
        dep_date = parse_flight_date(m.group("dep_date"))
        arr_date = parse_flight_date(m.group("arr_date"))
        if not dep_date or not arr_date:
            continue

        dep_dt = _build_datetime(dep_date, m.group("dep_time"))
        arr_dt = _build_datetime(arr_date, m.group("arr_time"))

        dep_iata = _resolve_iata(m.group("dep_name").strip())
        arr_iata = _resolve_iata(m.group("arr_name").strip())

        if not dep_iata or not arr_iata:
            logger.debug(
                "BA: could not resolve IATA for %r / %r",
                m.group("dep_name"),
                m.group("arr_name"),
            )
            continue

        flight = _make_flight_dict(
            rule,
            m.group("fn").replace(" ", ""),
            dep_iata,
            arr_iata,
            dep_dt,
            arr_dt,
            booking_ref,
            passenger,
        )
        if flight:
            flights.append(flight)

    if flights:
        logger.debug("British Airways: extracted %d flight(s)", len(flights))
    return flights
