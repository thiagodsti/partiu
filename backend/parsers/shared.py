"""
Shared utilities for BS4-based flight email extractors.
"""

import logging
import math
import re
from datetime import datetime, date as date_type, timezone

logger = logging.getLogger(__name__)


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
    return dt.replace(tzinfo=timezone.utc)


def _build_datetime(date_obj: date_type, time_str: str) -> datetime | None:
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
    full_text = subject + "\n" + _get_text(soup)
    m = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|Buchungscode|Buchungsnummer|"
        r"reservation\s*code|confirmation\s*code)[:\s\[]+([A-Z0-9]{5,8})",
        full_text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"Booking\s*:\s*([A-Z0-9]{5,8})", full_text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


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
                    "SELECT iata_code, latitude, longitude FROM airports"
                    " WHERE iata_code IN (?, ?)",
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
        h = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 6371 * 2 * math.asin(math.sqrt(h))
    except Exception:
        return 1.0
