"""
Shared utilities for BS4-based flight email extractors.
"""

import logging
import math
import re
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from functools import lru_cache

logger = logging.getLogger(__name__)


def normalize_fn(fn: str) -> str:
    """Strip spaces and non-breaking spaces from a flight number."""
    return fn.replace(" ", "").replace("\xa0", "")


def fix_overnight(dep_dt: datetime, arr_dt: datetime) -> datetime:
    """If arrival is before departure (overnight crossing), add one day to arrival."""
    if arr_dt < dep_dt:
        return arr_dt + timedelta(days=1)
    return arr_dt


@lru_cache(maxsize=512)
def resolve_iata(name: str) -> str:
    """Resolve an airport/city name string to a 3-letter IATA code.

    Search order:
      1. Trailing 3-letter uppercase code (e.g. "Stockholm Arlanda ARN")
      2. Exact match in airport_aliases after stripping parenthetical hints
      3. Each word/token tried against airport_aliases (handles hyphenated names)
      4. LIKE search on airports.name / exact on airports.city_name
      5. Word-by-word LIKE on airports (handles partial names like "Guarulhos Intl")
    """
    # 1. Trailing IATA code already present
    m = re.search(r"\b([A-Z]{3})$", name)
    if m:
        return m.group(1)

    # Strip parenthetical city hints: "Arlanda (Stockholm)" → "Arlanda"
    clean = re.sub(r"\s*\([^)]*\)", "", name).strip()
    name_lower = clean.lower().strip()
    orig_lower = name.lower().strip()

    try:
        from ..database import db_conn

        with db_conn() as conn:
            # 2. Exact alias match (try both cleaned and original)
            for candidate in dict.fromkeys([name_lower, orig_lower]):
                row = conn.execute(
                    "SELECT iata_code FROM airport_aliases WHERE alias = ?",
                    (candidate,),
                ).fetchone()
                if row:
                    return row["iata_code"]

            # 3. Word/token alias match — handles "Sicily-Catania", compound names
            tokens = [t for t in re.split(r"[\s\-()+]", name_lower) if len(t) >= 3]
            for tok in reversed(tokens):
                row = conn.execute(
                    "SELECT iata_code FROM airport_aliases WHERE alias = ?",
                    (tok,),
                ).fetchone()
                if row:
                    return row["iata_code"]

            # 4. LIKE on airports.name, exact on airports.city_name
            row = conn.execute(
                "SELECT iata_code FROM airports "
                "WHERE lower(name) LIKE ? OR lower(city_name) = ? LIMIT 1",
                (f"%{name_lower}%", name_lower),
            ).fetchone()
            if row:
                return row["iata_code"]

            # 5. Word-by-word LIKE (handles "Guarulhos Intl", "Rome Fiumicino", etc.)
            _SKIP = {"intl", "airport", "international", "intern", "city"}
            sig_tokens = [t for t in tokens if t not in _SKIP and len(t) >= 4]
            for tok in reversed(sig_tokens):
                row = conn.execute(
                    "SELECT iata_code FROM airports "
                    "WHERE lower(name) LIKE ? OR lower(city_name) LIKE ? LIMIT 1",
                    (f"%{tok}%", f"%{tok}%"),
                ).fetchone()
                if row:
                    return row["iata_code"]
    except Exception:
        pass

    return ""


def _extract_booking_ref_text(text: str) -> str:
    """Extract a booking / PNR reference from a plain-text string."""
    m = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|Buchungscode|Buchungsnummer|Reservierungscode|"
        r"reservation\s*code|confirmation\s*(?:code|number))[:\s\[]+([A-Z0-9]{5,8})",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"Booking\s*:\s*([A-Z0-9]{5,8})", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _get_text(tag) -> str:
    """Get clean text from a BS4 element, collapsing whitespace."""
    if tag is None:
        return ""
    text = tag.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _make_aware(dt: datetime) -> datetime:
    """Ensure a naive datetime is timezone-aware (UTC). No-op if already aware."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


def _build_datetime(date_obj: date_type | None, time_str: str) -> datetime | None:
    """Combine a date and 'HH:MM' string into a timezone-aware UTC datetime."""
    if not date_obj or not time_str:
        return None
    try:
        h, m = map(int, time_str.split(":"))
        return _make_aware(datetime(date_obj.year, date_obj.month, date_obj.day, h, m))
    except (ValueError, TypeError):
        return None


def _make_flight_dict(
    rule,
    flight_number: str,
    dep_airport: str,
    arr_airport: str,
    dep_dt,
    arr_dt,
    booking_ref: str = "",
    passenger: str = "",
) -> dict | None:
    """
    Build a flight data dict from extracted fields.
    Returns None if any required field is missing.
    """
    if not all([flight_number, dep_airport, arr_airport, dep_dt, arr_dt]):
        return None
    return {
        "airline_name": rule.airline_name,
        "airline_code": rule.airline_code,
        "flight_number": flight_number,
        "departure_airport": dep_airport,
        "arrival_airport": arr_airport,
        "departure_datetime": dep_dt,
        "arrival_datetime": arr_dt,
        "booking_reference": booking_ref,
        "passenger_name": passenger,
        "seat": "",
        "cabin_class": "",
        "departure_terminal": "",
        "arrival_terminal": "",
        "departure_gate": "",
        "arrival_gate": "",
    }


def _extract_booking_reference(soup, subject: str = "") -> str:
    """Extract a booking / PNR reference code from the email subject and body."""
    return _extract_booking_ref_text(subject + "\n" + _get_text(soup))


def _extract_passenger_name(soup) -> str:
    """Extract passenger name from greeting or passenger-list marker."""
    text = _get_text(soup)

    m = re.search(
        r"(?:Lista\s+de\s+passageiros|passenger\s*(?:list|name)|"
        r"Passagier|Reisender|passager|passasjer)"
        r"[\s:]*[-•·]?\s*"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    m = re.search(
        r"(?:Ol[áa]|Hello|Hola)\s+(?:<b[^>]*>)?\s*([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)",
        text,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _airport_distance(iata_a: str, iata_b: str) -> float:
    """Return great-circle distance in km between two airports. Falls back to 1.0."""
    try:
        from ..database import db_conn

        with db_conn() as conn:
            rows = {
                r["iata_code"]: r
                for r in conn.execute(
                    "SELECT iata_code, latitude, longitude FROM airports WHERE iata_code IN (?, ?)",
                    (iata_a.upper(), iata_b.upper()),
                ).fetchall()
            }
        a, b = rows.get(iata_a.upper()), rows.get(iata_b.upper())
        if not a or not b or a["latitude"] is None or b["latitude"] is None:
            return 1.0
        lat1 = math.radians(a["latitude"])
        lon1 = math.radians(a["longitude"])
        lat2 = math.radians(b["latitude"])
        lon2 = math.radians(b["longitude"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371 * 2 * math.asin(math.sqrt(h))
    except Exception:
        return 1.0
