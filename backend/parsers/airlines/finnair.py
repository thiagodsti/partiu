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
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from ..shared import _get_text, _make_flight_dict

logger = logging.getLogger(__name__)

_MONTHS_SHORT = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _parse_ddmon(s: str, year: int) -> datetime | None:
    """Parse '29Jul' or '29JUL' → datetime."""
    m = re.match(r"^(\d{1,2})([A-Za-z]{3})$", s.strip())
    if not m:
        return None
    day = int(m.group(1))
    mon = _MONTHS_SHORT.get(m.group(2).lower())
    if not mon:
        return None
    try:
        return datetime(year, mon, day, tzinfo=UTC)
    except ValueError:
        return None


def _build_dt(base: datetime, time_str: str) -> datetime | None:
    try:
        h, m = map(int, time_str.strip().split(":"))
        return base.replace(hour=h, minute=m)
    except (ValueError, TypeError):
        return None


def _resolve_iata(name: str) -> str:
    """Look up IATA code by airport/city name via DB."""
    base = re.sub(r"\s*\(.*?\)\s*", "", name).strip()
    terms: list[str] = []
    if base:
        terms.append(base)
    for w in base.split():
        if len(w) >= 3 and w not in terms:
            terms.append(w)
    try:
        from ...database import db_conn

        with db_conn() as conn:
            for term in terms:
                row = conn.execute(
                    "SELECT iata_code FROM airports WHERE name LIKE ? LIMIT 1",
                    (f"%{term}%",),
                ).fetchone()
                if row:
                    return row["iata_code"]
                row = conn.execute(
                    "SELECT iata_code FROM airports WHERE city_name LIKE ? LIMIT 1",
                    (f"%{term}%",),
                ).fetchone()
                if row:
                    return row["iata_code"]
    except Exception as e:
        logger.debug("Finnair: IATA lookup failed for %r: %s", name, e)
    return ""


def _extract_year(subject: str, email_date: datetime | None) -> int:
    """Extract year from subject (e.g. 'DEP: 29JUL2024') or email date."""
    m = re.search(r"DEP:\s*\d+\w+(\d{4})", subject, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if email_date:
        return email_date.year
    return datetime.now(UTC).year


def _extract_route_pairs_from_baggage(text: str) -> list[tuple[str, str]]:
    """
    Extract IATA pairs from baggage policy section.
    E.g. 'ARNHEL' → ('ARN', 'HEL'), 'HELARN' → ('HEL', 'ARN')
    """
    pairs: list[tuple[str, str]] = []
    # Find "Baggage Policy" section
    idx = text.find("Baggage Policy")
    if idx < 0:
        idx = text.find("BAGGAGE POLICY")
    if idx < 0:
        return pairs
    section = text[idx : idx + 500]
    # Match 6-uppercase-letter strings (two IATA codes concatenated)
    for m in re.finditer(r"\b([A-Z]{3})([A-Z]{3})\b", section):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def _parse_itinerary_text(text: str, year: int, rule) -> list[dict]:
    """
    Parse the Itinerary section of the Finnair e-ticket.

    The table columns after BS4 text extraction appear as separate lines
    (one value per line) within each row block. The structure is:

      FROM_CITY_NAME        ← e.g. "STOCKHOLM ARLANDA"
      TO_CITY_NAME          ← e.g. "HELSINKI HELSINKI VANTAA"
      AY0806                ← flight number
      Z                     ← class
      29Jul                 ← date
      07:15                 ← departure time
      09:15                 ← arrival time
      Ok                    ← status
      ...extra fields...

    In anonymized fixtures, city names are replaced. We fall back to
    the baggage policy IATA pairs.
    """
    # Find the Itinerary section
    iti_idx = text.find("Itinerary")
    if iti_idx < 0:
        iti_idx = text.find("ITINERARY")
    if iti_idx < 0:
        return []

    # Extract text from Itinerary section until Baggage Policy
    bag_idx = text.find("Baggage Policy", iti_idx)
    if bag_idx < 0:
        bag_idx = text.find("BAGGAGE", iti_idx)
    section = text[iti_idx:bag_idx] if bag_idx > iti_idx else text[iti_idx : iti_idx + 2000]

    # Skip the header line "From To Flight Class Date Departure Arrival ..."
    header_m = re.search(
        r"From\s+To\s+Flight\s+Class\s+Date\s+Departure\s+Arrival",
        section,
        re.IGNORECASE,
    )
    if header_m:
        section = section[header_m.end() :]

    # Booking reference
    booking_m = re.search(
        r"Booking\s+Reference[:\s]+([A-Z0-9]{5,8})",
        text,
        re.IGNORECASE,
    )
    booking_ref = booking_m.group(1) if booking_m else ""

    # Passenger name
    passenger_m = re.search(
        r"Passenger\s*\n+\s*([A-Za-z][A-Za-z\s]+?)\s*(?:\(ADT\)|\n)",
        text,
    )
    passenger = passenger_m.group(1).strip().title() if passenger_m else ""

    # AY flight numbers present in section
    fn_re = re.compile(r"\b(AY\s*\d{3,5})\b")
    fn_matches = list(fn_re.finditer(section))
    if not fn_matches:
        return []

    # Get IATA pairs from baggage policy section (fallback for anonymized fixtures)
    route_pairs = _extract_route_pairs_from_baggage(text)

    flights: list[dict] = []
    for leg_idx, fn_m in enumerate(fn_matches):
        fn = fn_m.group(1).replace(" ", "")

        # The row data surrounds the flight number:
        # lines before fn_m: from_city, to_city
        # lines after fn_m: class, date, dep_time, arr_time, status...
        before = section[max(0, fn_m.start() - 300) : fn_m.start()]
        after = section[fn_m.end() : fn_m.end() + 300]

        # Find date, dep time, arr time after flight number
        # Lines: class(single letter), date(DDMon), dep_time(HH:MM), arr_time(HH:MM)
        tokens_after = [t.strip() for t in after.split("\n") if t.strip()]
        date_str = dep_time = arr_time = ""
        class_char = ""
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

        base_dt = _parse_ddmon(date_str, year)
        if not base_dt:
            continue
        dep_dt = _build_dt(base_dt, dep_time)
        arr_dt = _build_dt(base_dt, arr_time)
        if not dep_dt or not arr_dt:
            continue

        # Try to get city names from lines before the flight number
        lines_before = [ln.strip() for ln in before.split("\n") if ln.strip()]
        # Last 2 non-empty lines should be from_city, to_city
        city_lines = [ln for ln in lines_before if not re.match(r"^[A-Z]{2}\d{3,5}$", ln)]
        # Filter out known non-city lines
        city_lines = [
            ln
            for ln in city_lines
            if not re.match(r"^\d", ln)
            and not re.search(
                r"(Fare Basis|Operated|Marketed|Terminal|Ok|NVB|NVA|check-in)", ln, re.IGNORECASE
            )
            and len(ln) > 2
        ]

        dep_iata = arr_iata = ""

        # Try baggage policy IATA pairs first (reliable, not anonymized)
        if leg_idx < len(route_pairs):
            dep_iata, arr_iata = route_pairs[leg_idx]

        # If no baggage pairs, try city name DB lookup
        if not dep_iata or not arr_iata:
            if len(city_lines) >= 2:
                dep_city = city_lines[-2]
                arr_city = city_lines[-1]
                if re.match(r"^[A-Z]{3}$", dep_city):
                    dep_iata = dep_city
                else:
                    dep_iata = _resolve_iata(dep_city)
                if re.match(r"^[A-Z]{3}$", arr_city):
                    arr_iata = arr_city
                else:
                    arr_iata = _resolve_iata(arr_city)

        if not dep_iata or not arr_iata:
            logger.debug("Finnair: could not resolve IATA for flight %s (leg %d)", fn, leg_idx)
            continue

        flight = _make_flight_dict(
            rule,
            fn,
            dep_iata,
            arr_iata,
            dep_dt,
            arr_dt,
            booking_ref,
            passenger,
        )
        if flight:
            if class_char:
                flight["cabin_class"] = class_char
            flights.append(flight)

    return flights


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Finnair e-ticket email."""
    subject = email_msg.subject or ""
    email_date = email_msg.date
    year = _extract_year(subject, email_date)

    body = email_msg.body or ""

    # Try plain text first
    flights = _parse_itinerary_text(body, year, rule)
    if flights:
        logger.debug("Finnair: extracted %d flight(s) from plain text", len(flights))
        return flights

    # Fall back to HTML
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        html_text = _get_text(soup)
        flights = _parse_itinerary_text(html_text, year, rule)
        if flights:
            logger.debug("Finnair: extracted %d flight(s) from HTML", len(flights))
            return flights

        # Try raw HTML text with newlines preserved
        html_text_nl = soup.get_text(separator="\n", strip=True)
        flights = _parse_itinerary_text(html_text_nl, year, rule)
        if flights:
            logger.debug("Finnair: extracted %d flight(s) from HTML (newline)", len(flights))
            return flights

    return []
