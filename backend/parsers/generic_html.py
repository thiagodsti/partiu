"""
Generic HTML flight extractor.

Extracts flight data from any HTML email by finding flight-number anchors
and searching a surrounding window for IATA codes, times, and dates.

Used as a fallback BEFORE the LLM when no custom extractor matches or
when a custom extractor returns empty results.

Guardrails to prevent false positives:
  - Both IATA codes validated against the airports DB
  - dep ≠ arr
  - Departure date not more than +2 years in the future (past flights are always allowed)
  - Flight number must match [A-Z]{2}\\d{3,5}
  - Both departure and arrival times must be present
"""

import logging
import re
from datetime import UTC, datetime
from datetime import date as date_type
from functools import lru_cache

from bs4 import BeautifulSoup

from .engine import parse_flight_date
from .shared import (
    _extract_booking_ref_text,
    _extract_passenger_text,
    _make_flight_dict,
    fix_overnight,
    normalize_fn,
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Flight number: 2 alphanumeric chars (at least one letter) + optional space/NBSP + 3-5 digits.
# Covers all IATA airline codes: AA, W6, W9, 4U, 9W, etc.
# We don't maintain an airline-code DB, so we keep the regex permissive and rely on
# downstream airport validation (both dep/arr must exist in the airports table) to
# discard false positives.
_FN_RE = re.compile(r"\b((?=[A-Z0-9]*[A-Z])[A-Z0-9]{2}[\s\xa0]*\d{3,5})\b")
# Compact single-line format: "AF 871 / 12NOV Cape Town - Paris CDG 07:55 19:15"
# Airline code + FN + "/" + DDMON[YYYY] + dep-city + "-" + arr-city + dep-time + arr-time
_COMPACT_FLIGHT_RE = re.compile(
    r"\b([A-Z]{2})\s+(\d{3,5})\s*/\s*"  # airline code + flight number + /
    r"(\d{1,2}[A-Z]{3}(?:\d{2,4})?)"  # DDMON, DDMONYY, or DDMONYYYY
    r"\s+(.+?)\s*-\s*(.+?)\s+"  # dep city - arr city
    r"(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})",  # dep time + arr time
    re.IGNORECASE,
)
# Exact HH:MM (may also have h suffix like Lufthansa "06:45 h")
_TIME_RE = re.compile(r"^(\d{1,2}:\d{2})(?:[\s\xa0]*h)?$")
# Combined time+date like "21:00 - 13 Apr 2025" (ITA Airways format)
_TIME_DATE_RE = re.compile(r"^(\d{1,2}:\d{2})\s*[-–]\s*(.+)$")
# Combined date+time like "03.04.2024 - 20:25" (Austrian format)
_DATE_TIME_RE = re.compile(r"^(.+?)\s*[-–]\s*(\d{1,2}:\d{2})$")
# Combined date+time without separator: "14/05/2026 09:35" (Wizz Air, etc.)
# Numeric date portion: DD/MM/YYYY, YYYY-MM-DD, DD.MM.YYYY
_DATE_TIME_SPACE_RE = re.compile(
    r"^(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})"
    r"\s+(\d{1,2}:\d{2})$"
)
# Route pair: "BCN-LTN" or "BCN–LTN" — two IATA codes separated by a dash
_ROUTE_PAIR_RE = re.compile(r"^([A-Z]{3})\s*[-–]\s*([A-Z]{3})$")
# Zero-width characters produced by some email clients (e.g. Lufthansa)
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]")
# Lines to skip when looking for IATA codes (labels, not airports)
_SKIP_IATA_RE = re.compile(
    r"(?:terminal|gate|seat|class|status|confirm|boarding|depart|arriv|"
    r"economy|business|first|premium|check.?in|flight\s*(?:number|no\.?)|"
    r"passenger|baggage|booking|reserv|oper|marketed|codeshare|total|price|"
    r"duration|stopp?|layover|overnight|meal|snack|fare)",
    re.IGNORECASE,
)


@lru_cache(maxsize=2048)
def _is_valid_iata(code: str) -> bool:
    """Return True if *code* exists in the airports table.

    Returns False (conservative) when the DB is unavailable so that the
    generic parser doesn't emit noise in test environments without a DB.
    """
    try:
        from ..database import db_conn

        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM airports WHERE iata_code = ?", (code.upper(),)
            ).fetchone()
            return row is not None
    except Exception:
        return False


def _iata_from_line(line: str) -> str:
    """Try to extract a valid airport IATA code from a single text line.

    Checks, in order:
      1. Code in parentheses: "(ARN)" or "(BCN)" — always trusted, skip-list ignored
      2. Standalone 3-letter uppercase token (validated against airports DB)
      3. City-name resolution via resolve_iata() — only for short, clean lines

    Returns '' when nothing valid is found.
    """
    line = line.strip()
    if not line:
        return ""

    # 1. Code in parentheses — most reliable signal; bypass skip-list
    m = re.search(r"\(([A-Z]{3})\)", line)
    if m:
        code = m.group(1)
        return code if _is_valid_iata(code) else ""

    # From here on apply the skip-list and other guards
    if len(line) > 45:
        return ""
    if _SKIP_IATA_RE.search(line):
        return ""
    # Skip pure numbers or time-like values
    if re.match(r"^[\d:.\s]+$", line):
        return ""

    # 2. Standalone 3-letter uppercase
    if re.match(r"^[A-Z]{3}$", line):
        return line if _is_valid_iata(line) else ""

    # 3. City name resolution — only for lines that look like proper city/airport names:
    #    must contain at least one alphabetic word of 4+ chars, no time patterns,
    #    no digits (avoids matching "salin", "Diego", random short strings)
    if (
        re.search(r"[A-Za-z]{4,}", line)
        and not re.search(r"\d{2}:\d{2}", line)
        and not re.match(r"^\d{1,2}\s+\w+\s+\d{4}$", line)  # date-like
        and not re.match(r"^[A-Za-z]{1,6}$", line)  # single short word (first names, etc.)
    ):
        code = resolve_iata(line)
        if code and _is_valid_iata(code):
            return code

    return ""


def _scan_window(
    lines: list[str],
    fn_line: int,
    win_start: int,
    win_end: int,
) -> tuple[list[str], list[str], list]:
    """Scan lines[win_start:win_end], skipping fn_line, and collect IATAs, times, dates."""
    iatas: list[str] = []
    times: list[str] = []
    dates: list = []
    seen_iatas: set[str] = set()

    for i in range(win_start, win_end):
        if i == fn_line:
            continue
        line = lines[i]

        # Time?
        m = _TIME_RE.match(line)
        if m:
            times.append(m.group(1))
            continue

        # Combined time+date like "21:00 - 13 Apr 2025"?
        m = _TIME_DATE_RE.match(line)
        if m:
            times.append(m.group(1))
            d = parse_flight_date(m.group(2).strip())
            if d is not None:
                dates.append(d)
            continue

        # Combined date+time like "03.04.2024 - 20:25"?
        m = _DATE_TIME_RE.match(line)
        if m:
            d = parse_flight_date(m.group(1).strip())
            if d is not None:
                dates.append(d)
                times.append(m.group(2))
                continue

        # Combined date+time without separator: "14/05/2026 09:35"?
        m = _DATE_TIME_SPACE_RE.match(line)
        if m:
            d = parse_flight_date(m.group(1).strip())
            if d is not None:
                dates.append(d)
                times.append(m.group(2))
                continue

        # Date?
        d = parse_flight_date(line)
        if d is not None:
            dates.append(d)
            continue

        # Route pair "BCN-LTN"? Extract both codes at once.
        m = _ROUTE_PAIR_RE.match(line)
        if m:
            for code in (m.group(1), m.group(2)):
                if _is_valid_iata(code) and code not in seen_iatas:
                    iatas.append(code)
                    seen_iatas.add(code)
            continue

        # IATA?
        code = _iata_from_line(line)
        if code and code not in seen_iatas:
            iatas.append(code)
            seen_iatas.add(code)

    return iatas, times, dates


class _SimpleRule:
    """Minimal rule-like object inferred from a flight number."""

    def __init__(self, airline_code: str) -> None:
        self.airline_code = airline_code
        self.airline_name = airline_code


def _parse_ddmon_year(token: str, ref_date) -> date_type | None:
    """Parse a DDMON token (e.g. '12NOV') inferring year from *ref_date*.

    Also handles DDMONYY and DDMONYYYY by delegating to parse_flight_date.
    """
    d = parse_flight_date(token)
    if d:
        return d
    if not ref_date:
        return None
    if not re.match(r"^\d{1,2}[A-Za-z]{3}$", token):
        return None
    ref_year = (
        ref_date.year if isinstance(ref_date, (date_type, datetime)) else ref_date.date().year
    )
    # Try current year then previous year
    for year in (ref_year, ref_year - 1, ref_year + 1):
        d = parse_flight_date(token + str(year))
        if d:
            return d
    return None


def _extract_compact_flights(
    lines: list[str],
    booking_ref: str,
    email_date,
    rule,
    today: date_type,
) -> list[dict]:
    """Extract flights from compact single-line format.

    Handles: ``AF 871 / 12NOV Cape Town - Paris CDG 07:55 19:15``

    Each line encodes the complete flight: airline, number, date, dep/arr
    city names, and times.  City names are resolved to IATA codes via
    resolve_iata().
    """
    flights: list[dict] = []
    seen_keys: set[tuple] = set()

    for line in lines:
        m = _COMPACT_FLIGHT_RE.search(line)
        if not m:
            continue

        airline_code = m.group(1).upper()
        fn = normalize_fn(f"{airline_code}{m.group(2)}")
        date_token = m.group(3)
        dep_city = m.group(4).strip()
        arr_city = m.group(5).strip()
        dep_time_str = m.group(6)
        arr_time_str = m.group(7)

        dep_date = _parse_ddmon_year(date_token, email_date)
        if dep_date is None:
            continue

        if (dep_date - today).days > 730:
            continue

        dep_iata = _iata_from_line(dep_city)
        if not dep_iata:
            dep_iata_raw = resolve_iata(dep_city)
            dep_iata = dep_iata_raw if dep_iata_raw and _is_valid_iata(dep_iata_raw) else ""
        arr_iata = _iata_from_line(arr_city)
        if not arr_iata:
            arr_iata_raw = resolve_iata(arr_city)
            arr_iata = arr_iata_raw if arr_iata_raw and _is_valid_iata(arr_iata_raw) else ""

        if not dep_iata or not arr_iata or dep_iata == arr_iata:
            continue

        try:
            h, mv = map(int, dep_time_str.split(":"))
            dep_dt = datetime(dep_date.year, dep_date.month, dep_date.day, h, mv, tzinfo=UTC)
            h2, m2 = map(int, arr_time_str.split(":"))
            arr_dt = datetime(dep_date.year, dep_date.month, dep_date.day, h2, m2, tzinfo=UTC)
        except (ValueError, TypeError):
            continue

        arr_dt = fix_overnight(dep_dt, arr_dt)

        key = (fn, dep_iata, arr_iata)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        effective_rule = rule if rule is not None else _SimpleRule(airline_code)
        flight = _make_flight_dict(
            effective_rule, fn, dep_iata, arr_iata, dep_dt, arr_dt, booking_ref
        )
        if flight:
            flights.append(flight)

    return flights


def _extract_from_lines(
    lines: list[str],
    booking_ref: str,
    email_date,
    rule,
    today,
) -> list[dict]:
    """Core extraction logic: scan *lines* for flight number anchors and build flight dicts."""
    fn_positions: list[tuple[int, str]] = []
    seen_fns: set[str] = set()
    for i, line in enumerate(lines):
        m = _FN_RE.search(line)
        if m:
            fn = normalize_fn(m.group(1))
            if fn not in seen_fns:
                fn_positions.append((i, fn))
                seen_fns.add(fn)

    if not fn_positions:
        return []

    flights: list[dict] = []
    seen_keys: set[tuple] = set()

    for leg_idx, (fn_line, fn) in enumerate(fn_positions):
        prev_fn_line = fn_positions[leg_idx - 1][0] if leg_idx > 0 else 0
        next_fn_line = (
            fn_positions[leg_idx + 1][0] if leg_idx + 1 < len(fn_positions) else len(lines)
        )
        win_start = max(fn_line - 15, prev_fn_line)
        win_end = min(fn_line + 20, next_fn_line)

        iatas, times, dates = _scan_window(lines, fn_line, win_start, win_end)

        if len(iatas) < 2:
            logger.debug("Generic: fewer than 2 IATAs for %s, skip", fn)
            continue
        if len(times) < 2:
            logger.debug("Generic: fewer than 2 times for %s, skip", fn)
            continue

        dep_iata, arr_iata = iatas[0], iatas[1]
        if dep_iata == arr_iata:
            continue

        dep_date = dates[0] if dates else None
        arr_date = dates[1] if len(dates) >= 2 else dep_date
        if dep_date is None and email_date:
            dep_date = email_date.date()
            arr_date = dep_date
        if dep_date is None:
            logger.debug("Generic: no date for %s, skip", fn)
            continue

        if (dep_date - today).days > 730:
            logger.debug("Generic: date %s too far in future for %s", dep_date, fn)
            continue

        try:
            h, m_val = map(int, times[0].split(":"))
            dep_dt = datetime(dep_date.year, dep_date.month, dep_date.day, h, m_val, tzinfo=UTC)
            h2, m2 = map(int, times[1].split(":"))
            arr_d = arr_date or dep_date
            arr_dt = datetime(arr_d.year, arr_d.month, arr_d.day, h2, m2, tzinfo=UTC)
        except (ValueError, TypeError):
            logger.debug("Generic: bad time for %s", fn)
            continue

        arr_dt = fix_overnight(dep_dt, arr_dt)

        key = (fn, dep_iata, arr_iata)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        effective_rule = rule if rule is not None else _SimpleRule(fn[:2])
        flight = _make_flight_dict(
            effective_rule, fn, dep_iata, arr_iata, dep_dt, arr_dt, booking_ref
        )
        if flight:
            flights.append(flight)

    # If window scan found nothing, try compact single-line format
    if not flights:
        flights = _extract_compact_flights(lines, booking_ref, email_date, rule, today)

    return flights


def extract_generic_html(email_msg, rule=None) -> list[dict]:
    """Extract flights from any HTML email using flight-number anchoring.

    Tries the HTML body first; falls back to the plain-text body when the
    HTML yields nothing (e.g. Norwegian/SAS plain-text confirmation emails).

    Args:
        email_msg: EmailMessage with html_body and/or body populated.
        rule: Matched airline rule (if any). Used to fill airline_name/code.
               When None, the airline code is inferred from the flight number.

    Returns:
        List of flight dicts (may be empty when nothing plausible is found).
    """
    today = datetime.now(UTC).date()
    subject = email_msg.subject or ""

    # --- Try HTML body ---
    if email_msg.html_body:
        soup = BeautifulSoup(email_msg.html_body, "lxml")
        text_nl = soup.get_text(separator="\n", strip=True)
        lines = [
            _ZW_RE.sub("", ln).replace("\xa0", " ").strip()
            for ln in text_nl.split("\n")
            if ln.strip()
        ]
        lines = [ln for ln in lines if ln]
        if lines:
            booking_ref = _extract_booking_ref_text(subject + "\n" + text_nl)
            flights = _extract_from_lines(lines, booking_ref, email_msg.date, rule, today)
            if flights:
                logger.info(
                    "Generic HTML: extracted %d flight(s) from '%s'",
                    len(flights),
                    subject[:60],
                )
                _enrich_metadata(flights, subject + "\n" + text_nl)
                return flights

    # --- Fallback: plain-text body ---
    if email_msg.body:
        text_plain = email_msg.body
        lines = [
            _ZW_RE.sub("", ln).replace("\xa0", " ").strip()
            for ln in text_plain.split("\n")
            if ln.strip()
        ]
        lines = [ln for ln in lines if ln]
        if lines:
            booking_ref = _extract_booking_ref_text(subject + "\n" + text_plain)
            flights = _extract_from_lines(lines, booking_ref, email_msg.date, rule, today)
            if flights:
                logger.info(
                    "Generic text: extracted %d flight(s) from '%s'",
                    len(flights),
                    subject[:60],
                )
                _enrich_metadata(flights, subject + "\n" + text_plain)
                return flights

    return []


def _enrich_metadata(flights: list[dict], text: str) -> None:
    """Fill in passenger_name on extracted flights using generic text patterns.

    Called after the primary extraction so any field already set by the
    airline-specific parser (or the compact-format path) is preserved.
    Seat is intentionally not set here — for multi-leg itineraries we cannot
    tell which seat belongs to which flight; BCBP boarding-pass parsing handles
    that later.
    """
    passenger = _extract_passenger_text(text)
    if passenger:
        for f in flights:
            if not f.get("passenger_name"):
                f["passenger_name"] = passenger
