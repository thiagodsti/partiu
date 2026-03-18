"""
Flight email parsing engine.

Main entry point: extract_flights_from_email()

Flow:
  1. Try BS4 (HTML) extraction via the per-airline extractor.
  2. Fall back to the airline's custom regex extractor (LATAM, SAS/Norwegian).
  3. Fall back to generic body_pattern regex matching defined in the rule.
"""

import calendar
import logging
import re
from datetime import datetime, date as date_type, timezone

from .builtin_rules import get_builtin_rules
from .email_connector import EmailMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Multilingual month-name → month-number map
# ---------------------------------------------------------------------------

def _build_month_map() -> dict[str, int]:
    """
    Build a lowercase month-name → month-number mapping.

    English names and abbreviations are generated from the standard library so
    we don't have to hardcode them. Only the non-English extras are listed
    explicitly, grouped by language.
    """
    mapping: dict[str, int] = {}

    # English — full names ("january") and 3-letter abbreviations ("jan")
    for n in range(1, 13):
        mapping[calendar.month_name[n].lower()] = n
        mapping[calendar.month_abbr[n].lower()] = n
    mapping["sept"] = 9  # common 4-letter variant not produced by calendar

    # Non-English month names (only entries not already covered by English)
    _EXTRA: dict[str, int] = {
        # Portuguese
        "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
        "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
        "fev": 2, "abr": 4, "mai": 5, "ago": 8, "set": 9, "out": 10, "dez": 12,
        # Spanish
        "enero": 1, "febrero": 2, "marzo": 3, "mayo": 5,
        "junio": 6, "julio": 7, "septiembre": 9,
        "octubre": 10, "noviembre": 11, "diciembre": 12,
        "ene": 1, "dic": 12,
        # German
        "märz": 3, "oktober": 10, "dezember": 12, "mär": 3,
        # Scandinavian (Swedish / Norwegian / Danish)
        "marts": 3, "maj": 5, "juni": 6, "juli": 7, "augusti": 8, "des": 12,
    }
    mapping.update(_EXTRA)
    return mapping

MONTH_MAP = _build_month_map()


def parse_flight_date(raw: str) -> date_type | None:
    """
    Parse a date string that may use multilingual month names.
    Handles formats like "16 de mar. de 2026", "16 Mar 2026", "2026-03-16".
    """
    raw = raw.strip()

    # ISO and common numeric formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # "16 de mar. de 2026" or "16 Mar 2026"
    m = re.match(r"(\d{1,2})\s+(?:de\s+)?([A-Za-zÀ-ÿ]+)\.?\s+(?:de\s+)?(\d{4})", raw)
    if m:
        month = MONTH_MAP.get(m.group(2).lower().rstrip("."))
        if month:
            try:
                return date_type(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass

    # "Mar 16, 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            try:
                return date_type(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                pass

    # Last resort: Python's strptime with locale month names
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def match_rule_to_email(email_msg: EmailMessage, rules):
    """
    Find the first airline rule matching the email's sender (and optionally subject).

    Also checks From:/Subject: lines embedded in forwarded message headers, so
    emails forwarded via Gmail ("---------- Forwarded message ---------") still
    match the original sender's rule.
    """
    senders = [email_msg.sender] + _extract_forwarded_senders(email_msg.body)
    subjects = [email_msg.subject] + _extract_forwarded_subjects(email_msg.body)

    for rule in rules:
        try:
            if not any(re.search(rule.sender_pattern, s, re.IGNORECASE) for s in senders):
                continue
            if rule.subject_pattern:
                if not any(re.search(rule.subject_pattern, s, re.IGNORECASE) for s in subjects):
                    continue
            return rule
        except re.error as e:
            logger.warning("Invalid regex in rule %s: %s", rule.airline_name, e)
    return None


def _extract_forwarded_senders(body: str) -> list[str]:
    """Extract From: addresses from forwarded-message headers in the email body."""
    return re.findall(r'^From:\s*(.+)$', body[:5000], re.MULTILINE)


def _extract_forwarded_subjects(body: str) -> list[str]:
    """Extract Subject: lines from forwarded-message headers in the email body."""
    return re.findall(r'^Subject:\s*(.+)$', body[:5000], re.MULTILINE)


def extract_flights_from_email(email_msg: EmailMessage, rule) -> list[dict]:
    """
    Extract flight data from an email that has been matched to an airline rule.

    Tries three strategies in order:
      1. BS4 (HTML) extraction — most accurate when an HTML body is present.
      2. Custom regex extractor — per-airline plain-text fallback (LATAM, SAS/Norwegian).
      3. Generic body_pattern regex — defined directly on the rule object.
    """
    # 1. BS4 extraction
    if email_msg.html_body:
        from .airlines import extract_with_bs4
        bs4_result = extract_with_bs4(email_msg.html_body, rule, email_msg)
        if bs4_result:
            return bs4_result

    # 2. Custom per-airline regex fallback
    extractor = getattr(rule, "custom_extractor", "")
    if extractor == "latam":
        from .airlines.latam import extract_regex
        return extract_regex(email_msg, rule)
    if extractor in ("sas", "norwegian"):
        from .airlines.sas import extract_regex
        return extract_regex(email_msg, rule)

    # 3. Generic body_pattern regex (used by airlines without a custom extractor)
    return _extract_generic(email_msg, rule)


def try_generic_pdf_extraction(email_msg: EmailMessage) -> list[dict]:
    """
    Last-resort extraction for emails that matched no rule.
    Tries to pull flight data directly from any PDF attachment using
    common itinerary patterns (time + IATA + date + flight-number + time + IATA).

    Returns [] when nothing plausible is found, so callers can safely ignore it.
    """
    if not email_msg.pdf_attachments:
        return []

    from .email_connector import _extract_text_from_pdf
    pdf_text = '\n'.join(
        t for b in email_msg.pdf_attachments
        if (t := _extract_text_from_pdf(b))
    )
    if not pdf_text:
        return []

    return _extract_generic_pdf(pdf_text, email_msg)


def _extract_generic(email_msg: EmailMessage, rule) -> list[dict]:
    """
    Generic regex-based extractor driven by rule.body_pattern named groups.

    Expected named groups: flight_number, departure_airport, arrival_airport,
    departure_date, departure_time, arrival_date, arrival_time, booking_reference,
    passenger_name, seat, cabin_class, departure_terminal, arrival_terminal,
    departure_gate, arrival_gate.
    """
    body = email_msg.body
    flights_data = []

    shared_booking = _extract_booking_ref(email_msg.subject + "\n" + body)
    shared_passenger = _extract_passenger(body)

    _CABIN_MAP = {
        "economy": "economy", "eco": "economy", "y": "economy",
        "econômica": "economy", "económica": "economy",
        "premium economy": "premium_economy", "premium": "premium_economy", "w": "premium_economy",
        "business": "business", "j": "business", "c": "business", "ejecutiva": "business",
        "first": "first", "f": "first",
    }

    try:
        matches = list(re.finditer(rule.body_pattern, body, re.IGNORECASE | re.DOTALL))
    except re.error as e:
        logger.error("Regex error in rule %s body_pattern: %s", rule.airline_name, e)
        return flights_data

    if not matches:
        logger.debug("No body_pattern matches for rule '%s' in email %s", rule.airline_name, email_msg.message_id)
        return flights_data

    ref_year = email_msg.date.year if email_msg.date else datetime.now().year

    for match in matches:
        g = match.groupdict()

        raw_flight_num = g.get("flight_number", "").strip()
        if raw_flight_num and raw_flight_num.isdigit() and rule.airline_code:
            raw_flight_num = f"{rule.airline_code}{raw_flight_num}"

        flight_data = {
            "airline_name": rule.airline_name,
            "airline_code": rule.airline_code,
            "flight_number": raw_flight_num,
            "departure_airport": g.get("departure_airport", "").strip().upper(),
            "arrival_airport": g.get("arrival_airport", "").strip().upper(),
            "booking_reference": g.get("booking_reference", "").strip() or shared_booking,
            "passenger_name": g.get("passenger_name", "").strip() or shared_passenger,
            "seat": g.get("seat", "").strip(),
            "cabin_class": _CABIN_MAP.get(g.get("cabin_class", "").strip().lower(), ""),
            "departure_terminal": g.get("departure_terminal", "").strip(),
            "arrival_terminal": g.get("arrival_terminal", "").strip(),
            "departure_gate": g.get("departure_gate", "").strip(),
            "arrival_gate": g.get("arrival_gate", "").strip(),
        }

        dep_date_str = g.get("departure_date", "").strip()
        dep_time_str = g.get("departure_time", "").strip()

        # If no explicit date in the match, look for one in the preceding body text
        if not dep_date_str:
            ctx_dates = list(re.finditer(r"(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})", body[: match.start()]))
            if ctx_dates:
                dep_date_str = ctx_dates[-1].group(1)

        arr_date_str = g.get("arrival_date", "").strip() or dep_date_str
        arr_time_str = g.get("arrival_time", "").strip()

        dep_date = _parse_date_with_fallback(dep_date_str, rule, ref_year, email_msg)
        if dep_date is None or not dep_time_str:
            logger.warning("Cannot parse departure datetime: %r %r", dep_date_str, dep_time_str)
            continue

        dep_dt = _parse_time_on_date(dep_date, dep_time_str)
        if dep_dt is None:
            logger.warning("Bad departure time %r", dep_time_str)
            continue
        flight_data["departure_datetime"] = dep_dt

        arr_date = _parse_date_with_fallback(arr_date_str, rule, ref_year, email_msg) or dep_date
        if not arr_time_str:
            logger.warning("No arrival time found, skipping")
            continue
        arr_dt = _parse_time_on_date(arr_date, arr_time_str)
        if arr_dt is None:
            logger.warning("Bad arrival time %r", arr_time_str)
            continue
        flight_data["arrival_datetime"] = arr_dt

        if flight_data["flight_number"] and flight_data["departure_airport"] and flight_data["arrival_airport"]:
            flights_data.append(flight_data)
        else:
            logger.debug("Skipping incomplete flight match: %s", flight_data)

    return flights_data


def _extract_booking_ref(text: str) -> str:
    m = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|Buchungscode|Buchungsnummer|reservation\s*code|"
        r"confirmation\s*code|Reservierungscode)[:\s\[]+([A-Z0-9]{5,8})",
        text, re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _extract_passenger(body: str) -> str:
    m = re.search(
        r"(?:Lista\s+de\s+passageiros|passenger\s*(?:list|name)|"
        r"Passagier|Reisender|passager|passasjer)"
        r"[\s:]*\n\s*(?:[-•·]\s*)?"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:[ ]+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)+)",
        body, re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _parse_date_with_fallback(date_str: str, rule, ref_year: int, email_msg) -> date_type | None:
    """Parse a date string, trying the rule's date_format as a secondary format."""
    d = parse_flight_date(date_str)
    if d is None and date_str:
        try:
            d = datetime.strptime(date_str, rule.date_format).date()
        except (ValueError, TypeError):
            pass
    # Year 1900 means strptime used a format without a year — inject ref_year
    if d is not None and d.year == 1900:
        candidate = d.replace(year=ref_year)
        if email_msg.date and candidate < email_msg.date.date():
            candidate = d.replace(year=ref_year + 1)
        d = candidate
    return d


def _parse_time_on_date(date_obj: date_type, time_str: str) -> datetime | None:
    """Combine a date and HH:MM string into a timezone-aware UTC datetime."""
    try:
        h, m = time_str.split(":")
        dt = datetime(date_obj.year, date_obj.month, date_obj.day, int(h), int(m))
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Generic PDF fallback (no matched rule required)
# ---------------------------------------------------------------------------

# Pattern: HH:MM IATA  ...  date-line  ...  flight-number  ...  HH:MM IATA
# Each section allows a few intervening lines so it survives extra content
# (airport names, carrier info, etc.) without matching across unrelated blocks.
_GENERIC_PDF_RE = re.compile(
    r'^(\d{1,2}:\d{2})\s+([A-Z]{3})\b[^\n]*\n'   # dep time + dep IATA
    r'(?:[^\n]*\n){0,4}'                            # up to 4 content lines
    r'([^\n]*\b\d{4}\b[^\n]*)\n'                   # date line (contains a 4-digit year)
    r'(?:[^\n]*\n){0,4}'                            # up to 4 more lines
    r'[^\n]*\b([A-Z]{2}\s*\d{2,5})\b[^\n]*\n'     # flight number
    r'(?:[^\n]*\n){0,3}'                            # up to 3 more lines
    r'^(\d{1,2}:\d{2})\s+([A-Z]{3})\b',            # arr time + arr IATA
    re.MULTILINE,
)

_GENERIC_BOOKING_RE = re.compile(
    r'(?:booking\s*(?:ref|code|reference|number)|PNR|confirmation\s*(?:code|number)|'
    r'N[UÚ]MERO\s+DE\s+RESERVA|Buchungsnummer|Reservierungscode)'
    r'[:\s#]+([\w\s]{5,20})',
    re.IGNORECASE,
)

_GENERIC_PASSENGER_RE = re.compile(
    r'(?:Ms\.|Mr\.|Mrs\.|Miss)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ\s]+?)(?=\s+\d|\s*\n)',
)


def _extract_generic_pdf(pdf_text: str, email_msg: EmailMessage) -> list[dict]:
    """
    Extract flights from a PDF using common itinerary patterns.
    Used as a last resort when no airline rule matched the email.
    """
    booking_ref = ''
    m = _GENERIC_BOOKING_RE.search(pdf_text)
    if m:
        booking_ref = m.group(1).strip().replace(' ', '')

    passenger = ''
    m = _GENERIC_PASSENGER_RE.search(pdf_text)
    if m:
        passenger = m.group(1).strip()

    ref_year = email_msg.date.year if email_msg.date else datetime.now().year
    flights = []
    seen = set()  # deduplicate by (flight_number, dep_airport, arr_airport)

    for m in _GENERIC_PDF_RE.finditer(pdf_text):
        dep_time_str = m.group(1)
        dep_airport  = m.group(2)
        date_line    = m.group(3)
        flight_num   = m.group(4).replace(' ', '')
        arr_time_str = m.group(5)
        arr_airport  = m.group(6)

        # Skip if airports are identical (false positive)
        if dep_airport == arr_airport:
            continue

        # Skip duplicate matches (the Kiwi PDF repeats each segment twice)
        key = (flight_num, dep_airport, arr_airport)
        if key in seen:
            continue
        seen.add(key)

        # Extract a parseable date from the date line
        date_m = re.search(r'(\d{1,2}\s+\w+\.?\s+\d{4})', date_line)
        if not date_m:
            # Try DD/MM/YYYY
            date_m = re.search(r'(\d{1,2}/\d{2}/\d{4})', date_line)
        if not date_m:
            continue
        dep_date = parse_flight_date(date_m.group(1))
        if dep_date is None:
            # Year-less date — inject ref_year
            date_m2 = re.search(r'(\d{1,2}\s+\w+\.?)', date_line)
            if date_m2:
                dep_date = parse_flight_date(date_m2.group(1) + f' {ref_year}')
        if dep_date is None:
            continue

        dep_dt = _parse_time_on_date(dep_date, dep_time_str)
        if dep_dt is None:
            continue

        # Arrival date: same day unless time wraps past midnight
        dep_h = int(dep_time_str.split(':')[0])
        arr_h = int(arr_time_str.split(':')[0])
        arr_date = dep_date
        if arr_h < dep_h:
            from datetime import timedelta
            arr_date = dep_date + timedelta(days=1)
        arr_dt = _parse_time_on_date(arr_date, arr_time_str)
        if arr_dt is None:
            continue

        airline_code = flight_num[:2]
        flights.append({
            'airline_name': airline_code,   # best we can do without a rule
            'airline_code': airline_code,
            'flight_number': flight_num,
            'departure_airport': dep_airport,
            'arrival_airport': arr_airport,
            'departure_datetime': dep_dt,
            'arrival_datetime': arr_dt,
            'booking_reference': booking_ref,
            'passenger_name': passenger,
            'seat': '',
            'cabin_class': '',
            'departure_terminal': '',
            'arrival_terminal': '',
            'departure_gate': '',
            'arrival_gate': '',
        })

    if flights:
        logger.info(
            "Generic PDF fallback found %d flight(s) in email %s",
            len(flights), email_msg.message_id,
        )
    return flights
