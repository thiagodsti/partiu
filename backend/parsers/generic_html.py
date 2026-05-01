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

from bs4 import BeautifulSoup

from .engine import parse_flight_date
from .shared import (
    extract_booking_reference,
    extract_passenger,
    fix_overnight,
    is_valid_iata,
    make_flight_dict,
    normalize_fn,
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Flight number: 2 alphanumeric chars (at least one letter) + optional space/NBSP + 3-5 digits.
# Covers all IATA airline codes: AA, W6, W9, 4U, 9W, etc.
# We don't maintain an airline-code DB, so we keep the regex permissive and rely on
# downstream airport validation (both dep/arr must exist in the airports table) to
# discard false positives.
_flight_number_re = re.compile(r"\b((?=[A-Z0-9]*[A-Z])[A-Z0-9]{2}[\s\xa0]*\d{3,5})\b")
# Compact single-line format: "AF 871 / 12NOV Cape Town - Paris CDG 07:55 19:15"
# Airline code + FN + "/" + DDMON[YYYY] + dep-city + "-" + arr-city + dep-time + arr-time
_compact_flight_re = re.compile(
    r"\b([A-Z]{2})\s+(\d{3,5})\s*/\s*"  # airline code + flight number + /
    r"(\d{1,2}[A-Z]{3}(?:\d{2,4})?)"  # DDMON, DDMONYY, or DDMONYYYY
    r"\s+(.+?)\s*-\s*(.+?)\s+"  # dep city - arr city
    r"(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})",  # dep time + arr time
    re.IGNORECASE,
)
# Exact HH:MM (may also have h suffix like Lufthansa "06:45 h")
_time_re = re.compile(r"^(\d{1,2}:\d{2})(?:[\s\xa0]*h)?$")
# Combined time+date like "21:00 - 13 Apr 2025" (ITA Airways format)
_time_then_date_re = re.compile(r"^(\d{1,2}:\d{2})\s*[-–]\s*(.+)$")
# Combined date+time like "03.04.2024 - 20:25" (Austrian format)
_date_then_time_re = re.compile(r"^(.+?)\s*[-–]\s*(\d{1,2}:\d{2})$")
# Combined date+time without separator: "14/05/2026 09:35" (Wizz Air, etc.)
# Numeric date portion: DD/MM/YYYY, YYYY-MM-DD, DD.MM.YYYY
_date_time_space_re = re.compile(
    r"^(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})"
    r"\s+(\d{1,2}:\d{2})$"
)
# Route pair: "BCN-LTN" or "BCN–LTN" — two IATA codes separated by a dash
_route_pair_re = re.compile(r"^([A-Z]{3})\s*[-–]\s*([A-Z]{3})$")
# Compound time-time: "18:10 - 19:55" or "18:10 - 19:55 (02h 45min)"
# Extracts both departure and arrival times from a single line.
_time_dash_time_re = re.compile(r"^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})(?:\s*\(.*\))?$")
# Zero-width characters produced by some email clients (e.g. Lufthansa)
_zero_width_chars_re = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff]")
# Lines to skip when looking for IATA codes (labels, not airports)
_label_words_re = re.compile(
    r"(?:terminal|gate|seat|class|status|confirm|boarding|depart|arriv|"
    r"economy|business|first|premium|check.?in|flight\s*(?:number|no\.?)|"
    r"passenger|baggage|booking|reserv|oper|marketed|codeshare|total|price|"
    r"duration|stopp?|layover|overnight|meal|snack|fare)",
    re.IGNORECASE,
)


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
        return code if is_valid_iata(code) else ""

    # From here on apply the skip-list and other guards
    if len(line) > 45:
        return ""
    if _label_words_re.search(line):
        return ""
    # Skip pure numbers or time-like values
    if re.match(r"^[\d:.\s]+$", line):
        return ""

    # 2. Standalone 3-letter uppercase
    if re.match(r"^[A-Z]{3}$", line):
        return line if is_valid_iata(line) else ""

    # 3. City name resolution — only for lines that look like proper city/airport names:
    #    must contain at least one alphabetic word of 4+ chars, no time patterns,
    #    no digits (avoids matching "salin", "Batman", random short strings)
    if (
        re.search(r"[A-Za-z]{4,}", line)
        and not re.search(r"\d{2}:\d{2}", line)
        and not re.match(r"^\d{1,2}\s+\w+\s+\d{4}$", line)  # date-like
        and not re.match(r"^[A-Za-z]{1,6}$", line)  # single short word (first names, etc.)
    ):
        code = resolve_iata(line)
        if code and is_valid_iata(code):
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
        m = _time_re.match(line)
        if m:
            times.append(m.group(1))
            continue

        # Compound time-time: "18:10 - 19:55" or "18:10 - 19:55 (02h 45min)"
        m = _time_dash_time_re.match(line)
        if m:
            times.append(m.group(1))
            times.append(m.group(2))
            continue

        # Combined time+date like "21:00 - 13 Apr 2025"?
        m = _time_then_date_re.match(line)
        if m:
            times.append(m.group(1))
            d = parse_flight_date(m.group(2).strip())
            if d is not None:
                dates.append(d)
            continue

        # Combined date+time like "03.04.2024 - 20:25"?
        m = _date_then_time_re.match(line)
        if m:
            d = parse_flight_date(m.group(1).strip())
            if d is not None:
                dates.append(d)
                times.append(m.group(2))
                continue

        # Combined date+time without separator: "14/05/2026 09:35"?
        m = _date_time_space_re.match(line)
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
        m = _route_pair_re.match(line)
        if m:
            for code in (m.group(1), m.group(2)):
                if is_valid_iata(code) and code not in seen_iatas:
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
        m = _compact_flight_re.search(line)
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
            dep_iata = dep_iata_raw if dep_iata_raw and is_valid_iata(dep_iata_raw) else ""
        arr_iata = _iata_from_line(arr_city)
        if not arr_iata:
            arr_iata_raw = resolve_iata(arr_city)
            arr_iata = arr_iata_raw if arr_iata_raw and is_valid_iata(arr_iata_raw) else ""

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
        flight = make_flight_dict(
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
        m = _flight_number_re.search(line)
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
        flight = make_flight_dict(
            effective_rule, fn, dep_iata, arr_iata, dep_dt, arr_dt, booking_ref
        )
        if flight:
            flights.append(flight)

    # If window scan found nothing, try compact single-line format
    if not flights:
        flights = _extract_compact_flights(lines, booking_ref, email_date, rule, today)

    return flights


def _extract_schema_org(html: str, rule, email_date) -> list[dict]:
    """Extract flights from schema.org FlightReservation microdata.

    Many airlines embed structured data in ``<meta itemprop="...">`` tags
    following the schema.org FlightReservation vocabulary.  The typical
    sequence for one flight leg is::

        <meta itemprop="reservationNumber" content="ABC123">
        <meta itemprop="name" content="JOHN DOE">
        <meta itemprop="flightNumber" content="533">
        <meta itemprop="iataCode" content="SK">    <!-- airline -->
        <meta itemprop="iataCode" content="ARN">   <!-- departure -->
        <meta itemprop="iataCode" content="LHR">   <!-- arrival -->
        <meta itemprop="departureTime" content="2025-01-14">
        <meta itemprop="arrivalTime" content="2025-01-14T16:05:00+00:00">

    Returns a list of flight dicts or ``[]`` when no microdata is found.
    """
    soup = BeautifulSoup(html, "lxml")
    metas: list[tuple[str, str]] = [
        (str(m.get("itemprop", "")), str(m.get("content", "")))
        for m in soup.find_all("meta")
        if m.get("itemprop") and m.get("content")
    ]

    if not any(prop == "flightNumber" for prop, _ in metas):
        return []

    # Collect departure datetimes from "From:" blocks in HTML (TAP pattern)
    dep_datetime_re = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}:\d{2})")
    dep_datetimes: list[datetime] = []
    for dm in dep_datetime_re.finditer(html):
        context = html[max(0, dm.start() - 400) : dm.start()]
        if context.rfind("From:") >= context.rfind("To:"):
            from .engine import parse_flight_date

            dep_date = parse_flight_date(dm.group(1))
            if dep_date:
                full_dt = _build_dt_from_date_time(dep_date, dm.group(2))
                if full_dt:
                    dep_datetimes.append(full_dt)

    flights = []
    seen_keys: set[tuple] = set()
    leg_idx = 0
    i = 0
    while i < len(metas):
        prop, val = metas[i]
        if prop == "reservationNumber":
            booking_ref = val
            j = i + 1
            fn_digits = ""
            airline_code = ""
            iata_codes: list[str] = []
            dep_time_raw = arr_time_raw = seat = passenger = ""

            while j < len(metas):
                p2, v2 = metas[j]
                if p2 == "reservationNumber" and j > i:
                    break
                if p2 == "name" and not fn_digits and not passenger:
                    passenger = v2
                elif p2 == "flightNumber":
                    fn_digits = v2
                elif p2 == "iataCode":
                    iata_codes.append(v2)
                elif p2 == "departureTime":
                    dep_time_raw = v2
                elif p2 == "arrivalTime":
                    arr_time_raw = v2
                elif p2 == "airplaneSeat":
                    seat = v2
                j += 1

            # iata_codes: [airline, departure, arrival]
            if len(iata_codes) < 3 or not fn_digits:
                i = j
                continue

            airline_code = iata_codes[0]
            dep_iata, arr_iata = iata_codes[1], iata_codes[2]
            if not is_valid_iata(dep_iata) or not is_valid_iata(arr_iata):
                i = j
                continue
            if dep_iata == arr_iata:
                i = j
                continue

            flight_number = normalize_fn(f"{airline_code}{fn_digits}")

            # Parse arrival datetime
            arr_dt: datetime | None = None
            if arr_time_raw:
                try:
                    arr_dt = datetime.fromisoformat(arr_time_raw).replace(tzinfo=UTC)
                except ValueError:
                    from .engine import parse_flight_date

                    arr_date = parse_flight_date(arr_time_raw)
                    arr_dt = _build_dt_from_date_time(arr_date, "00:00") if arr_date else None
            if not arr_dt:
                i = j
                continue

            # Parse departure datetime (from span or ISO)
            dep_dt: datetime | None = None
            if leg_idx < len(dep_datetimes):
                dep_dt = dep_datetimes[leg_idx]
            elif dep_time_raw:
                try:
                    dep_dt = datetime.fromisoformat(dep_time_raw).replace(tzinfo=UTC)
                except ValueError:
                    from .engine import parse_flight_date

                    dep_date = parse_flight_date(dep_time_raw)
                    dep_dt = _build_dt_from_date_time(dep_date, "00:00") if dep_date else None
            if not dep_dt:
                i = j
                continue

            key = (flight_number, dep_iata, arr_iata)
            if key in seen_keys:
                i = j
                continue
            seen_keys.add(key)

            effective_rule = rule if rule is not None else _SimpleRule(airline_code)
            flight = make_flight_dict(
                effective_rule,
                flight_number,
                dep_iata,
                arr_iata,
                dep_dt,
                arr_dt,
                booking_ref,
                passenger,
            )
            if flight and seat:
                flight["seat"] = seat
            if flight:
                flights.append(flight)

            leg_idx += 1
            i = j
        else:
            i += 1

    return flights


def _build_dt_from_date_time(d, time_str: str) -> datetime | None:
    """Combine a date and 'HH:MM' string into a UTC datetime."""
    if not d or not time_str:
        return None
    try:
        h, m = map(int, time_str.split(":"))
        return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)
    except (ValueError, TypeError, AttributeError):
        return None


def extract_generic_html(email_msg, rule=None) -> list[dict]:
    """Extract flights from any HTML email using flight-number anchoring.

    Tries schema.org microdata first, then line-scanning on HTML body,
    then falls back to the plain-text body.

    Args:
        email_msg: EmailMessage with html_body and/or body populated.
        rule: Matched airline rule (if any). Used to fill airline_name/code.
               When None, the airline code is inferred from the flight number.

    Returns:
        List of flight dicts (may be empty when nothing plausible is found).
    """
    today = datetime.now(UTC).date()
    subject = email_msg.subject or ""

    # --- Try schema.org microdata (most structured, least ambiguous) ---
    if email_msg.html_body:
        flights = _extract_schema_org(email_msg.html_body, rule, email_msg.date)
        if flights:
            logger.info(
                "Generic schema.org: extracted %d flight(s) from '%s'",
                len(flights),
                subject[:60],
            )
            return flights

    # --- Try HTML body line-scanning ---
    if email_msg.html_body:
        from .shared import html_to_text

        text_nl = html_to_text(email_msg.html_body)
        lines = [ln for ln in text_nl.split("\n") if ln.strip()]
        lines = [ln for ln in lines if ln]
        if lines:
            booking_ref = extract_booking_reference(text_nl, subject)
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
            _zero_width_chars_re.sub("", ln).replace("\xa0", " ").strip()
            for ln in text_plain.split("\n")
            if ln.strip()
        ]
        lines = [ln for ln in lines if ln]
        if lines:
            booking_ref = extract_booking_reference(text_plain, subject)
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
    passenger = extract_passenger(text)
    if passenger:
        for f in flights:
            if not f.get("passenger_name"):
                f["passenger_name"] = passenger
