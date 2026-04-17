"""
Flight email parsing engine.

Main entry point: extract_flights_from_email()

Flow:
  1. Try the per-airline extractor (HTML, regex, PDF — handled internally).
  2. Also try the generic PDF extractor and merge any richer fields it finds.
"""

import calendar
import logging
import re
from datetime import UTC, datetime
from datetime import date as date_type

from ..utils import validate_flight_number
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
        "janeiro": 1,
        "fevereiro": 2,
        "março": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
        "fev": 2,
        "abr": 4,
        "mai": 5,
        "ago": 8,
        "set": 9,
        "out": 10,
        "dez": 12,
        # Spanish
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "septiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
        "ene": 1,
        "dic": 12,
        # German
        "märz": 3,
        "oktober": 10,
        "dezember": 12,
        "mär": 3,
        # Scandinavian (Swedish / Norwegian / Danish)
        "marts": 3,
        "maj": 5,
        "juni": 6,
        "juli": 7,
        "augusti": 8,
        "okt": 10,
        "des": 12,
    }
    mapping.update(_EXTRA)
    return mapping


MONTH_MAP = _build_month_map()


def parse_flight_date(raw: str) -> date_type | None:
    """
    Parse a date string that may use multilingual month names.
    Handles formats like "16 de mar. de 2026", "16 Mar 2026", "2026-03-16",
    and day-of-week prefixes like "Wed, 23 Apr 25".
    """
    raw = raw.strip()
    # Strip leading day-of-week: "Wed, 23 Apr 25" → "23 Apr 25"
    raw = re.sub(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+", "", raw, flags=re.IGNORECASE)

    # ISO and common numeric formats (with year)
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
    # Includes compact no-space variants (24JAN2019, 24JAN19) and 2-digit years
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d%b%Y", "%d%b%y", "%d %b %y"):
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

    from .builtin_rules import SUBJECT_PATTERN

    for rule in rules:
        try:
            if not any(re.search(rule.sender_pattern, s, re.IGNORECASE) for s in senders):
                continue
            if not any(re.search(SUBJECT_PATTERN, s, re.IGNORECASE) for s in subjects):
                continue
            return rule
        except re.error as e:
            logger.warning("Invalid regex in rule %s: %s", rule.airline_name, e)
    return None


def _extract_forwarded_senders(body: str) -> list[str]:
    """Extract From: addresses from forwarded-message headers in the email body."""
    return re.findall(r"^From:\s*(.+)$", body[:5000], re.MULTILINE)


def _extract_forwarded_subjects(body: str) -> list[str]:
    """Extract Subject: lines from forwarded-message headers in the email body."""
    return re.findall(r"^Subject:\s*(.+)$", body[:5000], re.MULTILINE)


def extract_flights_from_email(email_msg: EmailMessage, rule) -> list[dict]:
    """
    Extract flight data from an email that has been matched to an airline rule.

    Calls ``rule.extractor(email_msg, rule)`` — the per-airline unified callable
    set by ``get_builtin_rules()``.  Also runs the generic PDF extractor and
    merges any richer fields it finds.
    """
    extractor = getattr(rule, "extractor", None)
    if extractor is None:
        return []

    try:
        results = extractor(email_msg, rule)
    except Exception:
        logger.debug(
            "Extractor for '%s' raised an exception",
            rule.airline_name,
            exc_info=True,
        )
        results = []

    # Always also attempt generic PDF extraction and merge any richer data
    if email_msg.pdf_attachments:
        pdf_results = _try_generic_pdf(email_msg)
        results = _merge_flights(results, pdf_results)

    return results


def _try_generic_pdf(email_msg: EmailMessage) -> list[dict]:
    """Extract flights from PDF attachments using the generic pattern."""
    from .email_connector import _extract_text_from_pdf

    pdf_text = "\n".join(t for b in email_msg.pdf_attachments if (t := _extract_text_from_pdf(b)))
    return _extract_generic_pdf(pdf_text, email_msg) if pdf_text else []


def _merge_flights(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """
    Merge ``secondary`` results into ``primary`` by filling empty fields.

    Matches flights by (flight_number, departure_airport, arrival_airport).
    Flights in ``secondary`` that have no match in ``primary`` are appended.
    """
    if not primary:
        return secondary
    if not secondary:
        return primary

    def _key(f: dict):
        return (
            f.get("flight_number", "").replace(" ", ""),
            f.get("departure_airport", ""),
            f.get("arrival_airport", ""),
        )

    primary_map = {_key(f): f for f in primary}
    for sec in secondary:
        k = _key(sec)
        if k in primary_map:
            pri = primary_map[k]
            for field_name, val in sec.items():
                if val and not pri.get(field_name):
                    pri[field_name] = val
        else:
            primary.append(sec)

    return primary


def try_generic_html_extraction(email_msg: EmailMessage, rule=None) -> list[dict]:
    """
    Smart generic HTML fallback for emails with no matched rule (or failed extraction).

    Runs BEFORE the LLM fallback. Anchors on flight number tokens and searches
    a surrounding window for IATA codes, times, and dates.

    Returns [] when nothing plausible is found.
    """
    from .generic_html import extract_generic_html

    return extract_generic_html(email_msg, rule)


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

    pdf_text = "\n".join(t for b in email_msg.pdf_attachments if (t := _extract_text_from_pdf(b)))
    if not pdf_text:
        return []

    return _extract_generic_pdf(pdf_text, email_msg)


def _parse_time_on_date(date_obj: date_type, time_str: str) -> datetime | None:
    """Combine a date and HH:MM string into a timezone-aware UTC datetime."""
    try:
        h, m = time_str.split(":")
        dt = datetime(date_obj.year, date_obj.month, date_obj.day, int(h), int(m))
        return dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Generic PDF fallback (no matched rule required)
# ---------------------------------------------------------------------------

# Pattern: HH:MM IATA  ...  date-line  ...  flight-number  ...  HH:MM IATA
# Each section allows a few intervening lines so it survives extra content
# (airport names, carrier info, etc.) without matching across unrelated blocks.
_pdf_itinerary_re = re.compile(
    r"^(\d{1,2}:\d{2})\s+([A-Z]{3})\b[^\n]*\n"  # dep time + dep IATA
    r"(?:[^\n]*\n){0,4}"  # up to 4 content lines
    r"([^\n]*\b\d{4}\b[^\n]*)\n"  # date line (contains a 4-digit year)
    r"(?:[^\n]*\n){0,4}"  # up to 4 more lines
    r"[^\n]*\b([A-Z]{2}\s*\d{2,5})\b[^\n]*\n"  # flight number
    r"(?:[^\n]*\n){0,3}"  # up to 3 more lines
    r"^(\d{1,2}:\d{2})\s+([A-Z]{3})\b",  # arr time + arr IATA
    re.MULTILINE,
)

_booking_reference_re = re.compile(
    r"(?:booking\s*(?:ref|code|reference|number)|PNR|confirmation\s*(?:code|number)|"
    r"N[UÚ]MERO\s+DE\s+RESERVA|Buchungsnummer|Reservierungscode)"
    r"[:\s#]+([\w\s]{5,20})",
    re.IGNORECASE,
)

_passenger_name_re = re.compile(
    r"(?:Ms\.|Mr\.|Mrs\.|Miss)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ\s]+?)(?=\s+\d|\s*\n)",
)


def _extract_generic_pdf(pdf_text: str, email_msg: EmailMessage) -> list[dict]:
    """
    Extract flights from a PDF using common itinerary patterns.
    Used as a last resort when no airline rule matched the email.
    """
    booking_ref = ""
    m = _booking_reference_re.search(pdf_text)
    if m:
        booking_ref = m.group(1).strip().replace(" ", "")

    passenger = ""
    m = _passenger_name_re.search(pdf_text)
    if m:
        passenger = m.group(1).strip()

    ref_year = email_msg.date.year if email_msg.date else datetime.now().year
    flights = []
    seen = set()  # deduplicate by (flight_number, dep_airport, arr_airport)

    for m in _pdf_itinerary_re.finditer(pdf_text):
        dep_time_str = m.group(1)
        dep_airport = m.group(2)
        date_line = m.group(3)
        flight_num = m.group(4).replace(" ", "")
        arr_time_str = m.group(5)
        arr_airport = m.group(6)

        # Skip if airports are identical (false positive)
        if dep_airport == arr_airport:
            continue

        # Skip duplicate matches (the Kiwi PDF repeats each segment twice)
        key = (flight_num, dep_airport, arr_airport)
        if key in seen:
            continue
        seen.add(key)

        # Extract a parseable date from the date line
        date_m = re.search(r"(\d{1,2}\s+\w+\.?\s+\d{4})", date_line)
        if not date_m:
            # Try DD/MM/YYYY
            date_m = re.search(r"(\d{1,2}/\d{2}/\d{4})", date_line)
        if not date_m:
            continue
        dep_date = parse_flight_date(date_m.group(1))
        if dep_date is None:
            # Year-less date — inject ref_year
            date_m2 = re.search(r"(\d{1,2}\s+\w+\.?)", date_line)
            if date_m2:
                dep_date = parse_flight_date(date_m2.group(1) + f" {ref_year}")
        if dep_date is None:
            continue

        dep_dt = _parse_time_on_date(dep_date, dep_time_str)
        if dep_dt is None:
            continue

        # Arrival date: same day unless time wraps past midnight
        dep_h = int(dep_time_str.split(":")[0])
        arr_h = int(arr_time_str.split(":")[0])
        arr_date = dep_date
        if arr_h < dep_h:
            from datetime import timedelta

            arr_date = dep_date + timedelta(days=1)
        arr_dt = _parse_time_on_date(arr_date, arr_time_str)
        if arr_dt is None:
            continue

        if not validate_flight_number(flight_num):
            logger.debug("Skipping invalid flight number from PDF %r", flight_num)
            continue
        airline_code = flight_num[:2]
        flights.append(
            {
                "airline_name": airline_code,  # best we can do without a rule
                "airline_code": airline_code,
                "flight_number": flight_num,
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
        )

    if flights:
        logger.info(
            "Generic PDF fallback found %d flight(s) in email %s",
            len(flights),
            email_msg.message_id,
        )
    return flights
