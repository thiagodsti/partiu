"""
Finnair (AY) flight extractor.

Handles e-ticket receipt emails sent via Amadeus GDS or directly from Finnair.

Email structure (plain text / HTML rendered as text):

  Booking Reference: TWJRQF
  ...
  Itinerary
  From To Flight Class Date Departure Arrival ...
  STOCKHOLM ARLANDA  HELSINKI HELSINKI VANTAA  AY0806  Z  29Jul  07:15  09:15  Ok ...
  HELSINKI HELSINKI VANTAA  STOCKHOLM ARLANDA  AY0813  Z  31Jul  15:55  15:55  Ok ...
  ...
  Baggage Policy
  ARNHEL   ← route code (IATA pair concatenated)
  HELARN

The table rows are separated by blank lines in the plain-text rendering.
Year is extracted from the subject line ("DEP: 29JUL2024") or email date.

Since city names may be anonymized in test fixtures, we also extract IATA codes
from the "Baggage Policy" section where routes appear as 6-char strings like "ARNHEL".
"""

import logging
import re

from bs4 import BeautifulSoup

from ..shared import (
    _build_datetime,
    enrich_flights,
    make_flight_dict,
    parse_date,
    resolve_iata,
)

logger = logging.getLogger(__name__)


def _extract_year(subject: str, email_date) -> int:
    """Extract year from subject (e.g. 'DEP: 29JUL2024') or email date."""
    m = re.search(r"DEP:\s*\d+\w+(\d{4})", subject, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return email_date.year if email_date else __import__("datetime").datetime.now().year


def _extract_route_pairs_from_baggage(text: str) -> list[tuple[str, str]]:
    """
    Extract IATA pairs from baggage policy section.
    E.g. 'ARNHEL' → ('ARN', 'HEL'), 'HELARN' → ('HEL', 'ARN')
    """
    pairs: list[tuple[str, str]] = []
    idx = text.find("Baggage Policy")
    if idx < 0:
        idx = text.find("BAGGAGE POLICY")
    if idx < 0:
        return pairs
    section = text[idx : idx + 500]
    for m in re.finditer(r"\b([A-Z]{3})([A-Z]{3})\b", section):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def _parse_itinerary_text(text: str, year: int, rule) -> list[dict]:
    """
    Parse the Itinerary section of the Finnair e-ticket.

    The table columns after BS4 text extraction appear as separate lines
    (one value per line) within each row block:

      FROM_CITY_NAME        ← e.g. "STOCKHOLM ARLANDA"
      TO_CITY_NAME          ← e.g. "HELSINKI HELSINKI VANTAA"
      AY0806                ← flight number
      Z                     ← class
      29Jul                 ← date (DDMon, no year)
      07:15                 ← departure time
      09:15                 ← arrival time
      Ok                    ← status
    """
    iti_idx = text.find("Itinerary")
    if iti_idx < 0:
        iti_idx = text.find("ITINERARY")
    if iti_idx < 0:
        return []

    bag_idx = text.find("Baggage Policy", iti_idx)
    if bag_idx < 0:
        bag_idx = text.find("BAGGAGE", iti_idx)
    section = text[iti_idx:bag_idx] if bag_idx > iti_idx else text[iti_idx : iti_idx + 2000]

    # Skip the header line
    header_m = re.search(
        r"From\s+To\s+Flight\s+Class\s+Date\s+Departure\s+Arrival",
        section,
        re.IGNORECASE,
    )
    if header_m:
        section = section[header_m.end() :]

    fn_re = re.compile(r"\b(AY\s*\d{3,5})\b")
    fn_matches = list(fn_re.finditer(section))
    if not fn_matches:
        return []

    route_pairs = _extract_route_pairs_from_baggage(text)

    flights: list[dict] = []
    for leg_idx, fn_m in enumerate(fn_matches):
        fn = fn_m.group(1).replace(" ", "")
        before = section[max(0, fn_m.start() - 300) : fn_m.start()]
        after = section[fn_m.end() : fn_m.end() + 300]

        # Parse tokens after flight number: class, date, dep_time, arr_time
        tokens_after = [t.strip() for t in after.split("\n") if t.strip()]
        date_str = dep_time = arr_time = class_char = ""
        for tok in tokens_after:
            if not class_char and re.match(r"^[A-Z]$", tok):
                class_char = tok
            elif not date_str and re.match(r"^\d{1,2}[A-Za-z]{3}$", tok):
                date_str = tok
            elif not dep_time and re.match(r"^\d{2}:\d{2}$", tok):
                dep_time = tok
            elif dep_time and not arr_time and re.match(r"^\d{2}:\d{2}$", tok):
                arr_time = tok
                break

        if not date_str or not dep_time or not arr_time:
            logger.debug("Finnair: incomplete row data for flight %s", fn)
            continue

        flight_date = parse_date(date_str, year)
        if not flight_date:
            continue

        # Resolve airports: baggage IATA pairs first, then city name lookup
        dep_iata = arr_iata = ""
        if leg_idx < len(route_pairs):
            dep_iata, arr_iata = route_pairs[leg_idx]

        if not dep_iata or not arr_iata:
            lines_before = [ln.strip() for ln in before.split("\n") if ln.strip()]
            city_lines = [
                ln
                for ln in lines_before
                if not re.match(r"^[A-Z]{2}\d{3,5}$", ln)
                and not re.match(r"^\d", ln)
                and not re.search(
                    r"(Fare Basis|Operated|Marketed|Terminal|Ok|NVB|NVA|check-in)",
                    ln,
                    re.IGNORECASE,
                )
                and len(ln) > 2
            ]
            if len(city_lines) >= 2:
                dep_city, arr_city = city_lines[-2], city_lines[-1]
                dep_iata = dep_city if re.match(r"^[A-Z]{3}$", dep_city) else resolve_iata(dep_city)
                arr_iata = arr_city if re.match(r"^[A-Z]{3}$", arr_city) else resolve_iata(arr_city)

        if not dep_iata or not arr_iata:
            logger.debug("Finnair: could not resolve IATA for flight %s (leg %d)", fn, leg_idx)
            continue

        flight = make_flight_dict(
            rule,
            fn,
            dep_iata,
            arr_iata,
            _build_datetime(flight_date, dep_time),
            _build_datetime(flight_date, arr_time),
        )
        if flight:
            if class_char:
                flight["cabin_class"] = class_char
            flights.append(flight)

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Finnair e-ticket email."""
    subject = email_msg.subject or ""
    year = _extract_year(subject, email_msg.date)
    body = email_msg.body or ""

    # Try plain text first
    flights = _parse_itinerary_text(body, year, rule)
    if flights:
        return enrich_flights(flights, body, subject)

    # Fall back to HTML
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        for separator in (" ", "\n"):
            html_text = (
                soup.get_text(separator=separator, strip=True)
                if separator == " "
                else soup.get_text(separator="\n", strip=True)
            )
            flights = _parse_itinerary_text(html_text, year, rule)
            if flights:
                return enrich_flights(flights, html_text, subject)

    return []
