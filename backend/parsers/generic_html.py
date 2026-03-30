"""
Generic HTML flight extractor.

Extracts flight data from any HTML email by finding flight-number anchors
and searching a surrounding window for IATA codes, times, and dates.

Used as a fallback BEFORE the LLM when no custom extractor matches or
when a custom extractor returns empty results.

Guardrails to prevent false positives:
  - Both IATA codes validated against the airports DB
  - dep ≠ arr
  - Departure date within ±2 years of today
  - Flight number must match [A-Z]{2}\\d{3,5}
  - Both departure and arrival times must be present
"""

import logging
import re
from datetime import UTC, datetime
from functools import lru_cache

from bs4 import BeautifulSoup

from .engine import parse_flight_date
from .shared import (
    _extract_booking_ref_text,
    _make_flight_dict,
    fix_overnight,
    normalize_fn,
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Flight number: two uppercase letters + optional space + 3-5 digits
_FN_RE = re.compile(r"\b([A-Z]{2}[\s\xa0]*\d{3,5})\b")
# Exact HH:MM (may also have h suffix like Lufthansa "06:45 h")
_TIME_RE = re.compile(r"^(\d{1,2}:\d{2})(?:\s*h)?$")
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
      1. Standalone 3-letter uppercase token (validated against airports DB)
      2. Code in parentheses: "(ARN)" or "(BGY)"
      3. City-name resolution via resolve_iata()

    Returns '' when nothing valid is found.
    """
    line = line.strip()
    if not line or len(line) > 45:
        return ""
    if _SKIP_IATA_RE.search(line):
        return ""
    # Skip pure numbers or time-like values
    if re.match(r"^[\d:.\s]+$", line):
        return ""

    # 1. Standalone 3-letter uppercase
    if re.match(r"^[A-Z]{3}$", line):
        return line if _is_valid_iata(line) else ""

    # 2. Code in parentheses
    m = re.search(r"\(([A-Z]{3})\)", line)
    if m:
        code = m.group(1)
        return code if _is_valid_iata(code) else ""

    # 3. City name resolution (skip lines that contain digits unless they look
    #    like "Guarulhos Intl" or similar; exclude date-like strings)
    if re.search(r"[A-Za-z]{3,}", line) and not re.search(r"\d{2}:\d{2}", line):
        # Don't try resolve_iata on lines that are clearly not city names
        if re.match(r"^\d{1,2}\s+\w+\s+\d{4}$", line):  # looks like a date
            return ""
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

        # Date?
        d = parse_flight_date(line)
        if d is not None:
            dates.append(d)
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


def extract_generic_html(email_msg, rule=None) -> list[dict]:
    """Extract flights from any HTML email using flight-number anchoring.

    Args:
        email_msg: EmailMessage with html_body populated.
        rule: Matched airline rule (if any). Used to fill airline_name/code.
               When None, the airline code is inferred from the flight number.

    Returns:
        List of flight dicts (may be empty when nothing plausible is found).
    """
    if not email_msg.html_body:
        return []

    soup = BeautifulSoup(email_msg.html_body, "lxml")
    text_nl = soup.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text_nl.split("\n") if ln.strip()]

    if not lines:
        return []

    booking_ref = _extract_booking_ref_text((email_msg.subject or "") + "\n" + text_nl)
    today = datetime.now(UTC).date()

    # --- Collect flight number positions (deduplicated) ---
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
        # Window: bounded by adjacent flight numbers to avoid cross-leg bleed
        prev_fn_line = fn_positions[leg_idx - 1][0] if leg_idx > 0 else 0
        next_fn_line = (
            fn_positions[leg_idx + 1][0] if leg_idx + 1 < len(fn_positions) else len(lines)
        )
        win_start = max(fn_line - 15, prev_fn_line)
        win_end = min(fn_line + 20, next_fn_line)

        iatas, times, dates = _scan_window(lines, fn_line, win_start, win_end)

        if len(iatas) < 2:
            logger.debug("Generic HTML: fewer than 2 IATAs for %s, skip", fn)
            continue
        if len(times) < 2:
            logger.debug("Generic HTML: fewer than 2 times for %s, skip", fn)
            continue

        dep_iata, arr_iata = iatas[0], iatas[1]
        if dep_iata == arr_iata:
            continue

        dep_date = dates[0] if dates else None
        arr_date = dates[1] if len(dates) >= 2 else dep_date
        if dep_date is None and email_msg.date:
            dep_date = email_msg.date.date()
            arr_date = dep_date
        if dep_date is None:
            logger.debug("Generic HTML: no date for %s, skip", fn)
            continue

        # Sanity: date within ±2 years
        if abs((dep_date - today).days) > 730:
            logger.debug("Generic HTML: date %s too far from today for %s", dep_date, fn)
            continue

        try:
            h, m_val = map(int, times[0].split(":"))
            dep_dt = datetime(dep_date.year, dep_date.month, dep_date.day, h, m_val, tzinfo=UTC)
            h2, m2 = map(int, times[1].split(":"))
            arr_d = arr_date or dep_date
            arr_dt = datetime(arr_d.year, arr_d.month, arr_d.day, h2, m2, tzinfo=UTC)
        except (ValueError, TypeError):
            logger.debug("Generic HTML: bad time for %s", fn)
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

    if flights:
        logger.info(
            "Generic HTML: extracted %d flight(s) from '%s'",
            len(flights),
            (email_msg.subject or "")[:60],
        )
    return flights
