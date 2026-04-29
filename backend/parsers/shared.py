"""
Shared utilities for flight email extractors.

Writing a new airline parser
----------------------------
1. Create ``backend/parsers/airlines/<airline>.py``
2. Implement ``extract(email_msg, rule) -> list[dict]``
3. Register in ``builtin_rules.py`` (add a dict entry — the extractor
   is resolved automatically from the module name).

Available helpers (import from ``backend.parsers.shared``):

  **Text extraction**
    get_email_text(email_msg)            → plain text (space-separated)
    get_email_text_newline(email_msg)    → plain text (newline-separated)
    get_ref_year(email_msg)              → reference year for date parsing

  **Flight scanning** (for emails with line-by-line structure)
    scan_flights(text, rule, ref_year)   → scans for flight blocks automatically

  **Metadata extraction**
    extract_booking_reference(text, subject)  → booking/PNR code
    extract_passenger(text)                   → passenger name
    extract_seat(text)                        → seat assignment
    enrich_flights(flights, text, subject)    → fills all three on flight dicts

  **Flight dict construction**
    make_flight_dict(rule, fn, dep, arr, dep_dt, arr_dt, ...)  → validated dict

  **Date/time helpers**
    parse_date(s, default_year)          → date from various formats
    _build_datetime(date, time_str)      → combine date + "HH:MM" → aware datetime
    fix_overnight(dep_dt, arr_dt)        → adds a day if arr < dep

  **Airport resolution**
    resolve_iata(name)                   → city/airport name → IATA code
    is_valid_iata(code)                  → check if code exists in airports DB

Simplest parser example (Ryanair)::

    from ..shared import enrich_flights, get_email_text, get_ref_year, scan_flights

    def extract(email_msg, rule) -> list[dict]:
        text = get_email_text(email_msg)
        flights = scan_flights(text, rule, get_ref_year(email_msg))
        return enrich_flights(flights, text, email_msg.subject)

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
    # "02/03/2026 13:20"  (space or non-breaking space — common in HTML emails)
    re.compile(r"(\d{2}/\d{2}/\d{4})[\s\xa0]+(\d{2}:\d{2})"),
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
    # "Flight Number: W9 5362"  (Wizz Air — space or NBSP inside the code)
    re.compile(r"Flight\s+Number:\s*([A-Z0-9]{1,3}[\s\xa0]\d{3,5})", re.IGNORECASE),
    # "Voo 4849" / "Vôo 4849"  (Portuguese label + number, same line)
    re.compile(r"(?:Voo|Vôo)\s+(\d{3,5})", re.IGNORECASE),
    # "Flight 4849"  (English label + number, same line)
    re.compile(r"Flight\s+(\d{3,5})", re.IGNORECASE),
    # Full IATA flight number alone on a line: "AD4849", "W95362"
    re.compile(r"^([A-Z]{1,3}\d{3,5})$"),
    # "QR 168" or "W9 5362" — code + space/NBSP + digits, alone on a line
    re.compile(r"^([A-Z]{1,3}[\s\xa0]\d{2,5})$"),
    # Bare digit-only number alone on a line: "4849"
    re.compile(r"^(\d{3,5})$"),
]

# IATA code in parentheses: "(BCN)", "Terminal 2 (BCN)"
_iata_in_parens_re = re.compile(r"\(([A-Z]{3})\)")

# Standalone IATA code on its own line: "BCN"
_standalone_iata_re = re.compile(r"^([A-Z]{3})$")

# Labeled departure/arrival times: "Departure time - 17:55" / "Arrival time – 20:35"
_departure_labeled_time_re = re.compile(r"Departure\s+time\s*[-–]\s*(\d{1,2}:\d{2})", re.IGNORECASE)
_arrival_labeled_time_re = re.compile(r"Arrival\s+time\s*[-–]\s*(\d{1,2}:\d{2})", re.IGNORECASE)


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
            # Normalize spaces and non-breaking spaces: "W9 5362" → "W95362"
            raw = m.group(1).strip().replace(" ", "").replace("\xa0", "")
            if raw.isdigit() and airline_code:
                return f"{airline_code}{raw}"
            return raw
    return ""


def extract_line_date_only(line: str, ref_year: int | None = None) -> date_type | None:
    """
    Try to parse a line as a standalone date with no time component.

    Returns ``None`` when the line already contains a time (handled by
    ``extract_line_datetime``) or when it cannot be interpreted as a date.
    Strips leading day-of-week prefixes ("Wed, 23 Apr 25" → "23 Apr 25").
    """
    from .engine import parse_flight_date

    # Skip lines that contain a time component — those belong to Strategy A
    if re.search(r"\b\d{1,2}:\d{2}\b", line):
        return None

    stripped = line.strip()
    # Strip leading day-of-week: "Wed, 23 Apr 25" → "23 Apr 25"
    stripped = re.sub(
        r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+", "", stripped, flags=re.IGNORECASE
    )

    d = parse_flight_date(stripped)
    if d:
        return d

    # Year-less "DD Mon" — inject ref_year
    if ref_year and re.match(r"^\d{1,2}\s+[A-Za-z]{3}\.?$", stripped):
        return parse_flight_date(f"{stripped} {ref_year}")

    return None


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


def scan_flights(text: str, rule, ref_year: int | None = None) -> list[dict]:
    """
    Generic flight scanner for emails where:
    - Flight numbers appear on dedicated lines (any pattern from _FLIGHT_NUM_LINE_PATTERNS)
    - Airport IATA codes appear in parentheses on nearby lines: "(BCN)"
    - Datetimes appear on nearby lines (any format from _DATETIME_LINE_PATTERNS)

    For each flight number found, scans a window of surrounding lines to collect
    two IATA codes and two datetimes (departure + arrival). Returns a list of
    flight dicts (booking_reference and passenger_name left empty for the caller
    to fill in).
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    seen_fns: set[str] = set()
    flights: list[dict] = []

    for i, line in enumerate(lines):
        fn = extract_line_flight_number(line, rule.airline_code)
        if not fn or fn in seen_fns:
            continue
        seen_fns.add(fn)

        # Build a window: 2 lines before + up to 15 after, stopping at the
        # next flight-number line so multi-leg emails don't bleed into each other.
        start = max(0, i - 2)
        end = i + 1
        while end < len(lines) and end - i <= 15:
            if end > i and extract_line_flight_number(lines[end], rule.airline_code):
                break
            end += 1
        window = lines[start:end]

        # Strategy A-IATA: parenthesised codes "(BCN)"
        iata_codes: list[str] = []
        for wl in window:
            iata_codes.extend(_iata_in_parens_re.findall(wl))

        # Fallback IATA: standalone 3-letter lines "BCN" (skip the flight-number line)
        if len(iata_codes) < 2:
            for j, wl in enumerate(window):
                m_iata = _standalone_iata_re.match(wl)
                if m_iata:
                    code = m_iata.group(1)
                    if code not in iata_codes:
                        iata_codes.append(code)

        # Strategy A-DT: combined date+time lines "02/03/2026 13:20"
        datetimes: list[tuple] = []
        for wl in window:
            result = extract_line_datetime(wl, ref_year)
            if result:
                datetimes.append(result)

        # Strategy B-DT: date-only line + labeled departure/arrival times.
        # Pre-collapse split-line formats ("Departure time -\n17:55") into one line
        # so that _departure_labeled_time_re can match them.
        if len(datetimes) < 2:
            collapsed: list[str] = []
            k = 0
            while k < len(window):
                wl = window[k]
                if (
                    k + 1 < len(window)
                    and re.search(r"(?:Departure|Arrival)\s+time\s*[-–]?\s*$", wl, re.IGNORECASE)
                    and re.match(r"^\d{1,2}:\d{2}$", window[k + 1])
                ):
                    collapsed.append(wl.rstrip() + " - " + window[k + 1])
                    k += 2
                else:
                    collapsed.append(wl)
                    k += 1

            date_only_b = None
            dep_time_b = None
            arr_time_b = None
            for wl in collapsed:
                if date_only_b is None:
                    d = extract_line_date_only(wl, ref_year)
                    if d:
                        date_only_b = d
                        continue
                if dep_time_b is None:
                    m_dep = _departure_labeled_time_re.search(wl)
                    if m_dep:
                        dep_time_b = m_dep.group(1)
                        continue
                if arr_time_b is None:
                    m_arr = _arrival_labeled_time_re.search(wl)
                    if m_arr:
                        arr_time_b = m_arr.group(1)
                        continue
            if date_only_b and dep_time_b and arr_time_b:
                datetimes = [(date_only_b, dep_time_b), (date_only_b, arr_time_b)]

        # Strategy C-DT: date-only line + first two standalone HH:MM lines after it.
        # Catches formats where times appear alone on their own lines without labels.
        if len(datetimes) < 2:
            date_only_c: date_type | None = None
            standalone_times: list[str] = []
            for wl in window:
                if date_only_c is None:
                    d = extract_line_date_only(wl, ref_year)
                    if d:
                        date_only_c = d
                    continue
                m_t = re.match(r"^(\d{1,2}:\d{2})$", wl)
                if m_t:
                    standalone_times.append(m_t.group(1))
                if len(standalone_times) == 2:
                    break
            if date_only_c and len(standalone_times) == 2:
                datetimes = [
                    (date_only_c, standalone_times[0]),
                    (date_only_c, standalone_times[1]),
                ]

        if len(iata_codes) < 2 or len(datetimes) < 2:
            continue

        dep_iata, arr_iata = iata_codes[0], iata_codes[1]
        if dep_iata == arr_iata:
            continue

        dep_dt = _build_datetime(datetimes[0][0], datetimes[0][1])
        arr_dt = _build_datetime(datetimes[1][0], datetimes[1][1])
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)

        flight = make_flight_dict(rule, fn, dep_iata, arr_iata, dep_dt, arr_dt)
        if flight:
            flights.append(flight)

    if flights:
        logger.debug("scan_flights: found %d flight(s) for %s", len(flights), rule.airline_name)
    return flights


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
    # BA: "e-ticket receipt J9CRT8:" — check first so subject beats body fallback
    m = re.search(r"\breceipt\s+(?-i:([A-Z0-9]{5,8}))\b", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(?:"
        r"C[óo]digo\s+de\s+reserva(?:\s*/\s*Booking\s+ref)?"  # PT/ES + bilingual
        r"|Referência\s+da\s+reserva"  # PT (TAP)
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
    # Kiwi / generic: numeric booking numbers like "NÚMERO DE RESERVA 755 885 086"
    # or "Booking number 123 456 789" — digits with optional spaces, 5–12 digits total.
    m = re.search(
        r"(?:N[UÚ]MERO\s+DE\s+RESERVA|N[úu]mero\s+de\s+reserva|Booking\s+number)"
        r"[:\s]+([\d][\d ]{3,14}[\d])",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().replace(" ", "")
    # ITA: "Booking code\n\n...\nGate\n\nKKEZ2E" boarding-pass table layout
    m = re.search(
        r"Booking\s+code[\s\S]{0,80}?Gate[\s\S]{0,20}?(?-i:([A-Z0-9]{5,8}))\b",
        text,
        re.IGNORECASE,
    )
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
    # "JOHN SMITH Booking reference ABC123" — Brussels Airlines / Lufthansa PDF header:
    # all-caps name on same line as "Booking reference", before the reference code.
    m = re.search(
        r"^([A-Z][A-Z ]{2,}?)\s+Booking reference\b",
        text,
        re.MULTILINE,
    )
    if m:
        return m.group(1).strip().title()

    # "Lista de passageiros: John Smith" / "Passenger list:\nJohn Smith"
    # Negative lookahead prevents matching "passenger name record (PNR)" in legal text.
    m = re.search(
        r"(?:Lista\s+de\s+passageiros|Passenger\s*list|Passenger\s*name(?!\s+record))"
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


@lru_cache(maxsize=2048)
def is_valid_iata(code: str) -> bool:
    """Return True if *code* is a known airport IATA code in the DB.

    Falls back to True when the DB is unavailable so that extraction is
    never silently blocked in environments without a seeded database.
    """
    try:
        from ..database import db_conn

        with db_conn() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM airports WHERE iata_code = ?", (code.upper(),)
                ).fetchone()
                is not None
            )
    except Exception:
        return True  # conservative: let extraction proceed when DB is absent


def parse_date(s: str, default_year: int | None = None) -> date_type | None:
    """Parse a date string, injecting *default_year* when no year is present.

    Delegates to ``parse_flight_date`` (ISO, DD/MM/YYYY, month-name variants,
    compact DDMonYYYY, day-of-week prefixes, etc.).  When the string contains
    no 4-digit year and *default_year* is provided, two injections are tried:
    space-separated (``"10 Nov 2024"``) and compact (``"23FEB2024"``).
    """
    from .engine import parse_flight_date

    s = s.strip()
    d = parse_flight_date(s)
    if d:
        return d

    if default_year and not re.search(r"\d{4}", s):
        d = parse_flight_date(f"{s} {default_year}")
        if d:
            return d
        d = parse_flight_date(f"{s}{default_year}")
        if d:
            return d

    return None


def make_flight_dict(
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
    Returns None if any required field is missing or either IATA code is
    not found in the airports database.
    """
    if not all([flight_number, dep_airport, arr_airport, dep_dt, arr_dt]):
        return None
    if not is_valid_iata(dep_airport) or not is_valid_iata(arr_airport):
        logger.debug(
            "Skipping flight %s: unrecognised IATA %s / %s",
            flight_number,
            dep_airport,
            arr_airport,
        )
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


# ---------------------------------------------------------------------------
# Public API — consistent names used by every parser
# ---------------------------------------------------------------------------


def get_email_text(email_msg) -> str:
    """Extract plain text from an email (HTML preferred, falls back to plain body)."""
    if email_msg.html_body:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(email_msg.html_body, "lxml")
        return soup.get_text(separator="\n", strip=True)
    return email_msg.body or ""


def extract_booking_reference(text: str, subject: str = "") -> str:
    """Extract a booking / PNR reference from email text and optional subject line."""
    combined = f"{subject}\n{text}" if subject else text
    return _extract_booking_ref_text(combined)


def extract_passenger(text: str) -> str:
    """Extract the passenger name from email text."""
    return _extract_passenger_text(text)


def extract_seat(text: str) -> str:
    """Extract the seat assignment from email text."""
    return _extract_seat_text(text)


def get_email_text_newline(email_msg) -> str:
    """Extract plain text from an email with newline separators.

    Preferred over ``get_email_text`` when the parser needs to process
    the text line-by-line (e.g. state machines, line-anchored regexes).
    """
    if email_msg.html_body:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(email_msg.html_body, "lxml")
        return soup.get_text(separator="\n", strip=True)
    return email_msg.body or ""


def get_ref_year(email_msg) -> int:
    """Return the reference year from the email date (current year as fallback).

    Most airline emails use partial dates (``"14 May"`` without a year).
    Use this to inject the missing year when calling ``parse_date``,
    ``scan_flights``, or ``extract_line_datetime``.
    """
    return email_msg.date.year if email_msg.date else datetime.now().year


def enrich_flights(flights: list[dict], text: str, subject: str = "") -> list[dict]:
    """Fill booking reference, passenger name, and seat on all flights.

    Extracts metadata from *text* (and optionally *subject*) and applies
    it to every flight dict whose field is still empty.  Seat is only
    set when there is exactly one flight (multi-leg seats are ambiguous
    without per-leg boarding-pass data).

    Returns *flights* unchanged (mutated in place) for easy chaining::

        return enrich_flights(flights, text, email_msg.subject)
    """
    if not flights:
        return flights
    booking_ref = extract_booking_reference(text, subject)
    passenger = extract_passenger(text)
    seat = extract_seat(text)
    single_leg = len(flights) == 1
    for f in flights:
        if not f.get("booking_reference"):
            f["booking_reference"] = booking_ref
        if not f.get("passenger_name"):
            f["passenger_name"] = passenger
        if single_leg and not f.get("seat"):
            f["seat"] = seat
    return flights


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
