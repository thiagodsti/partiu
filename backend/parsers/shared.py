"""
Shared utilities for BS4-based flight email extractors.

Pattern libraries
-----------------
Rather than each airline parser hard-coding its own date/time/flight-number
regexes, shared pattern lists are defined here and tried in sequence (most
specific first, least specific last).  When a new airline email reveals a new
format, add one entry here and every parser that calls the shared helpers
benefits automatically.
"""

import logging
import math
import re
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from functools import lru_cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared datetime patterns (date + time on the same line/token)
# ---------------------------------------------------------------------------
# Each pattern must capture group(1) = date string, group(2) = HH:MM time.
# The date string is passed directly to parse_flight_date / parse_date_str.
# Year-less patterns (marked with a comment) return just "DD/MM"; the helper
# injects the reference year before parsing.

_DATETIME_LINE_PATTERNS: list[re.Pattern] = [
    # "02/03/2026 - 13:20"  or  "02/03/2026 – 13:20"  (en-dash)
    re.compile(r"(\d{2}/\d{2}/\d{4})\s*[-–]\s*(\d{2}:\d{2})"),
    # "02/03/2026 13:20"  (space-only separator)
    re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})"),
    # "2026-03-02 13:20"  (ISO date)
    re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})"),
    # "2 Mar 2026 13:20"  or  "02 Mar 2026, 13:20"  (month-name)
    re.compile(r"(\d{1,2}\s+[A-Za-zÀ-ÿ]+\.?\s+\d{4})[,\s]+(\d{2}:\d{2})"),
    # "02/03 • 13:20"  or  "02/03 · 13:20"  (no year, bullet separator)
    re.compile(r"(\d{2}/\d{2})\s*[•·]\s*(\d{2}:\d{2})"),
    # "02/03 - 13:20"  or  "02/03 – 13:20"  (no year, dash separator)
    re.compile(r"(\d{2}/\d{2})\s*[-–]\s*(\d{2}:\d{2})"),
]

# ---------------------------------------------------------------------------
# Shared flight-number patterns (per-line)
# ---------------------------------------------------------------------------
# Tried in order. The first match wins.
# Caller is responsible for prepending airline_code when only digits are found.

_FLIGHT_NUM_LINE_PATTERNS: list[re.Pattern] = [
    # "Voo 4849" / "Vôo 4849"  (Portuguese label + number, same line)
    re.compile(r"(?:Voo|Vôo)\s+(\d{3,5})", re.IGNORECASE),
    # "Flight 4849"  (English label + number, same line)
    re.compile(r"Flight\s+(\d{3,5})", re.IGNORECASE),
    # Full IATA flight number alone on a line: "AD4849", "W95362"
    re.compile(r"^([A-Z]{1,3}\d{3,5})$"),
    # Bare digit-only number alone on a line: "4849"
    re.compile(r"^(\d{3,5})$"),
]


def extract_line_datetime(line: str, ref_year: int | None = None) -> tuple[date_type, str] | None:
    """
    Try all shared datetime patterns against a single line of text.

    Returns ``(date, time_str)`` where *date* is a fully resolved
    :class:`datetime.date` and *time_str* is ``"HH:MM"``.
    For year-less patterns (``DD/MM``), *ref_year* (defaulting to the
    current year) is injected before parsing.
    Returns ``None`` when no pattern matches.
    """
    # Import here to avoid circular import (engine imports shared)
    from .engine import parse_flight_date

    for pat in _DATETIME_LINE_PATTERNS:
        m = pat.search(line)
        if m:
            date_str, time_str = m.group(1), m.group(2)
            # Year-less "DD/MM" — inject reference year
            if re.match(r"^\d{2}/\d{2}$", date_str):
                year = ref_year or datetime.now().year
                date_str = f"{date_str}/{year}"
            d = parse_flight_date(date_str)
            if d:
                return d, time_str
    return None


def extract_line_flight_number(line: str, airline_code: str = "") -> str:
    """
    Try all shared flight-number patterns against a single line of text.

    Returns the flight number string (airline code already included), or
    an empty string when nothing matched.  Digit-only matches are prefixed
    with *airline_code* when one is provided.
    """
    for pat in _FLIGHT_NUM_LINE_PATTERNS:
        m = pat.search(line)
        if m:
            raw = m.group(1).strip()
            if raw.isdigit() and airline_code:
                return f"{airline_code}{raw}"
            return raw
    return ""


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
    """Extract a booking / PNR reference from a plain-text string.

    Covers all major airline label formats across English, Portuguese, Spanish,
    German, and Scandinavian.

    Design decisions:
    - Separator allows spaces, colons, brackets, hash, newlines, and an optional
      connecting word like "IS" (Norwegian: "YOUR BOOKING REFERENCE IS:\\nQAJV6E").
    - ``Reserv\\w{1,12}`` instead of just "Reservation" because test fixtures
      anonymise the label to "ReservTESTRF" (real emails always have "Reservation").
    - Sub-keywords for Ticket / Order / e-ticket are **required** (not optional)
      to avoid matching "Ticket details", "Order summary", etc.
    - The captured code uses ``(?-i:[A-Z0-9]{5,8})`` (inline no-IGNORECASE) so
      lowercase English words like "details", "secure", "price" are never captured
      — airline booking references are always uppercase alphanumeric.
    """
    m = re.search(
        r"(?:"
        r"C[óo]digo\s+de\s+reserva(?:\s*/\s*Booking\s+ref)?"  # PT/ES + bilingual
        r"|Referência\s+da\s+reserva"  # PT (TAP)
        r"|N[úu]mero\s+de\s+reserva"  # PT/ES (Kiwi)
        r"|booking\s*(?:ref(?:erence)?|code|number)"  # EN: all variants
        r"|Reserv\w{1,12}\b"  # Reservation, Reserva, ReservTESTRF…
        r"|Bokning(?:snummer)?"  # SV
        r"|PNR"  # Universal
        r"|Buchungscode|Buchungsnummer|Reservierungscode|Buchungsreferenz"  # DE
        r"|confirmation\s*(?:code|number)"  # EN
        r"|Flight\s+confirmation\s+code"  # EN (Wizz Air)
        r"|e-?ticket\s+(?:number|no\.?)"  # EN — sub-keyword required
        r"|Ticket\s+(?:number|no\.?)"  # EN — sub-keyword required
        r"|Order\s+(?:number|no\.?)"  # EN — sub-keyword required
        r")"
        r"[:\s\[\#\n]+"  # separator (colon / spaces / newlines)
        r"(?:is\b[:\s\n]*)?"  # optional connecting word "IS" (Norwegian format)
        r"(?-i:([A-Z0-9]{5,8}))\b",  # code must be uppercase — filters out common words
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # BA subject format: "Your e-ticket receipt J9CRT8:"
    m = re.search(r"\breceipt\s+(?-i:([A-Z0-9]{5,8}))\b", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Bare "Booking: XXXXX" without a sub-keyword
    m = re.search(r"\bBooking\s*:\s*(?-i:([A-Z0-9]{5,8}))\b", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_passenger_text(text: str) -> str:
    """Extract passenger name from any airline email plain text.

    Tries patterns in order of specificity — labeled references first (most
    reliable), greeting patterns last (first name only).
    """
    # "Lista de passageiros: John Smith" / "Passenger list:\nJohn Smith"
    m = re.search(
        r"(?:Lista\s+de\s+passageiros|Passenger\s*(?:list|name))"
        r"[\s:]*[-•·]?\s*"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # "Passageiro / Passenger: John Smith (ADT)" (TAP e-ticket)
    m = re.search(
        r"Passageiro\s*/\s*Passenger[:\s]+"
        r"([A-Za-zÀ-ÿ][a-zA-ZÀ-ÿ\s]+?)(?:\s*\(ADT\)|\n)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # "Passagier / Reisender / passager / passasjer: NAME" (DE/FR/NO/SV)
    m = re.search(
        r"(?:Passagier|Reisender|passager|passasjer)"
        r"[\s:]*[-•·]?\s*"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # "Mr / Mrs / Ms / Miss JOHN SMITH" — title guarantees this is a person
    m = re.search(
        r"(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)+)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # "Dear / Hello / Olá / Hola FIRSTNAME" — greeting (first name only)
    m = re.search(
        r"(?:Dear|Hello|Ol[áa]|Hola)\s+(?:<[^>]+>\s*)?([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]{2,})",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return ""


def _extract_seat_text(text: str) -> str:
    """Extract a seat assignment from any airline email plain text.

    Looks for a seat label (in multiple languages) followed by a seat code
    like ``12A``.  Returns an empty string when nothing is found.
    """
    m = re.search(
        r"(?:Seat|Asiento|Assento|Posto|Sitz|Si[eè]ge)"
        r"[\s:/*\n]+"
        r"(\d{1,3}[A-F])\b",
        text,
        re.IGNORECASE,
    )
    return m.group(1).strip().upper() if m else ""


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
