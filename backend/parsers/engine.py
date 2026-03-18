"""
Flight email parsing engine.
Applies airline rules (regex patterns) to email messages to extract flight data.

Adapted from AdventureLog parsers.py — Django dependencies removed.
Returns plain Python dicts (not ORM model instances).
"""

import logging
import re
from datetime import datetime, date as date_type, timedelta, timezone

from .builtin_rules import get_builtin_rules
from .email_connector import EmailMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Multilingual month-name map (lowercase, no trailing dot)
# ---------------------------------------------------------------------------
MONTH_MAP: dict[str, int] = {
    # English
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    # Portuguese
    "fev": 2,
    "fevereiro": 2,
    "março": 3,
    "abr": 4,
    "abril": 4,
    "mai": 5,
    "maio": 5,
    "ago": 8,
    "agosto": 8,
    "set": 9,
    "setembro": 9,
    "out": 10,
    "outubro": 10,
    "dez": 12,
    "dezembro": 12,
    "janeiro": 1,
    "junho": 6,
    "julho": 7,
    "novembro": 11,
    # Spanish
    "ene": 1,
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
    # German
    "mär": 3,
    "märz": 3,
    "okt": 10,
    "oktober": 10,
    "dezember": 12,
    # Scandinavian / Norwegian / Danish extras
    "maj": 5,
    "marts": 3,
    "juni": 6,
    "juli": 7,
    "augusti": 8,
    "des": 12,
}


def parse_flight_date(raw: str) -> date_type | None:
    """
    Parse a date string that may use Portuguese/Spanish/German/Scandinavian month
    names. Handles e.g. "16 de mar. de 2026", "16 Mar 2026", "2026-03-16".
    """
    raw = raw.strip()

    # ISO / numeric formats first
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # "16 de mar. de 2026"  or  "16 Mar 2026"
    m = re.match(r"(\d{1,2})\s+(?:de\s+)?([A-Za-zÀ-ÿ]+)\.?\s+(?:de\s+)?(\d{4})", raw)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower().rstrip(".")
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if month:
            try:
                return date_type(year, month, day)
            except ValueError:
                pass

    # English "Mar 16, 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        month_name = m.group(1).lower()
        day = int(m.group(2))
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if month:
            try:
                return date_type(year, month, day)
            except ValueError:
                pass

    # Last resort: strftime with current locale
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def _make_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def match_rule_to_email(email_msg: EmailMessage, rules):
    """
    Find the first matching airline rule for an email message.
    Checks sender_pattern and optionally subject_pattern.
    """
    for rule in rules:
        try:
            if not re.search(rule.sender_pattern, email_msg.sender, re.IGNORECASE):
                continue
            if rule.subject_pattern:
                if not re.search(
                    rule.subject_pattern, email_msg.subject, re.IGNORECASE
                ):
                    continue
            return rule
        except re.error as e:
            logger.warning("Invalid regex in rule %s: %s", rule.airline_name, e)
            continue
    return None


# ---------------------------------------------------------------------------
# LATAM custom extractor
# ---------------------------------------------------------------------------


def _extract_latam_flights(email_msg: EmailMessage, rule) -> list[dict]:
    """Custom LATAM extractor that handles connection flights."""
    body = email_msg.body
    flights_data: list[dict] = []

    shared_booking = ""
    booking_match = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|confirmation\s*code)[:\s\[]+([A-Z0-9]{5,8})",
        email_msg.subject + "\n" + body,
        re.IGNORECASE,
    )
    if booking_match:
        shared_booking = booking_match.group(1).strip()

    shared_passenger = ""
    passenger_match = re.search(
        r"(?:Lista\s+de\s+passageiros|passenger\s*(?:list|name))"
        r"[\s:]*[-•·]?\s*"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)",
        body,
        re.IGNORECASE,
    )
    if not passenger_match:
        passenger_match = re.search(
            r"(?:Ol[áa]|Hello|Hola)\s+(?:<b[^>]*>)?\s*([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)",
            body,
            re.IGNORECASE,
        )
    if passenger_match:
        shared_passenger = passenger_match.group(1).strip()

    _DATE_RE = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
    _TIME_RE = r"(\d{1,2}:\d{2})"
    _AIRPORT_RE = r"\(([A-Z]{3})\)"
    _FLIGHT_NUM_RE = r"([A-Z0-9]{2}\s*\d{3,5})(?!\w)"

    direction_starts = list(
        re.finditer(
            r"Voo de (?:ida|volta)|(?:Outbound|Return|Inbound)\s+(?:flight|journey)",
            body,
            re.IGNORECASE,
        )
    )

    if not direction_starts:
        trecho_starts = list(re.finditer(r"Trecho\s+\d+", body, re.IGNORECASE))
        if trecho_starts:
            sections = []
            for i, m in enumerate(trecho_starts):
                start = m.start()
                end = (
                    trecho_starts[i + 1].start()
                    if i + 1 < len(trecho_starts)
                    else len(body)
                )
                sections.append(body[start:end])
        else:
            itin_match = re.search(r"Itiner[áa]rio", body, re.IGNORECASE)
            sections = [body[itin_match.start() :] if itin_match else body]
    else:
        sections = []
        for i, m in enumerate(direction_starts):
            start = m.start()
            end = (
                direction_starts[i + 1].start()
                if i + 1 < len(direction_starts)
                else len(body)
            )
            sections.append(body[start:end])

    for section in sections:
        dep_match = re.search(
            _DATE_RE + r"\s+" + _TIME_RE + r".*?" + _AIRPORT_RE,
            section,
            re.DOTALL,
        )
        if not dep_match:
            continue

        dep_date_str = dep_match.group(1)
        dep_time_str = dep_match.group(2)
        dep_airport = dep_match.group(3)

        arr_matches = list(
            re.finditer(
                _DATE_RE + r"\s+" + _TIME_RE + r".*?" + _AIRPORT_RE,
                section,
                re.DOTALL,
            )
        )
        if len(arr_matches) < 2:
            flight_match = re.search(
                r"\("
                + re.escape(dep_airport)
                + r"\)\s+"
                + _FLIGHT_NUM_RE
                + r".*?"
                + _AIRPORT_RE,
                section,
            )
            if flight_match:
                flight_num = flight_match.group(1).strip()
                arr_airport = flight_match.group(2)
                fd = _make_latam_flight(
                    rule,
                    dep_date_str,
                    dep_time_str,
                    dep_airport,
                    dep_date_str,
                    dep_time_str,
                    arr_airport,
                    flight_num,
                    shared_booking,
                    shared_passenger,
                )
                if fd:
                    flights_data.append(fd)
            continue

        arr_match = arr_matches[-1]
        arr_date_str = arr_match.group(1)
        arr_time_str = arr_match.group(2)
        arr_airport = arr_match.group(3)

        connection_re = (
            r"Troca\s+de\s+avi[ãa]o\s+em:\s*"
            r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ\s]*?)\s*"
            r"\(([A-Z]{3})\)\s+"
            r"([A-Z0-9]{2}\s*\d{3,5})"
            r".*?"
            r"Tempo\s+de\s+espera:\s*(\d+)\s*hr?\s*(\d+)\s*min"
        )
        connections = list(
            re.finditer(connection_re, section, re.DOTALL | re.IGNORECASE)
        )

        first_flight_match = re.search(
            r"\(" + re.escape(dep_airport) + r"\)\s+" + _FLIGHT_NUM_RE,
            section,
        )
        first_flight_num = (
            first_flight_match.group(1).strip() if first_flight_match else ""
        )

        if connections:
            segments = []
            prev_airport = dep_airport

            first_conn = connections[0]
            conn_airport = first_conn.group(2)
            conn_flight = first_conn.group(3).strip()
            layover_h = int(first_conn.group(4))
            layover_m = int(first_conn.group(5))
            segments.append(
                {
                    "dep_airport": prev_airport,
                    "arr_airport": conn_airport,
                    "flight_number": first_flight_num,
                    "layover_after_minutes": layover_h * 60 + layover_m,
                    "next_flight": conn_flight,
                }
            )
            prev_airport = conn_airport

            for i in range(1, len(connections)):
                conn = connections[i]
                conn_airport = conn.group(2)
                conn_flight = conn.group(3).strip()
                layover_h = int(conn.group(4))
                layover_m = int(conn.group(5))
                segments.append(
                    {
                        "dep_airport": prev_airport,
                        "arr_airport": conn_airport,
                        "flight_number": segments[-1]["next_flight"],
                        "layover_after_minutes": layover_h * 60 + layover_m,
                        "next_flight": conn_flight,
                    }
                )
                prev_airport = conn_airport

            segments.append(
                {
                    "dep_airport": prev_airport,
                    "arr_airport": arr_airport,
                    "flight_number": segments[-1]["next_flight"],
                    "layover_after_minutes": 0,
                    "next_flight": "",
                }
            )

            dep_date = parse_flight_date(dep_date_str)
            arr_date = parse_flight_date(arr_date_str)
            if dep_date is None or arr_date is None:
                continue

            dep_h, dep_m_val = map(int, dep_time_str.split(":"))
            arr_h, arr_m_val = map(int, arr_time_str.split(":"))

            dep_dt = datetime(
                dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m_val
            )
            arr_dt = datetime(
                arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val
            )

            total_elapsed = (arr_dt - dep_dt).total_seconds()
            total_layover = sum(s["layover_after_minutes"] * 60 for s in segments)
            total_flight = total_elapsed - total_layover
            n_segments = len(segments)

            if total_flight <= 0 or n_segments == 0:
                continue

            flight_per_segment = total_flight / n_segments
            current_dt = dep_dt

            for seg in segments:
                seg_dep_dt = current_dt
                seg_arr_dt = seg_dep_dt + timedelta(seconds=flight_per_segment)

                flight_data = {
                    "airline_name": rule.airline_name,
                    "airline_code": rule.airline_code,
                    "flight_number": seg["flight_number"],
                    "departure_airport": seg["dep_airport"],
                    "arrival_airport": seg["arr_airport"],
                    "departure_datetime": _make_aware(seg_dep_dt),
                    "arrival_datetime": _make_aware(seg_arr_dt),
                    "booking_reference": shared_booking,
                    "passenger_name": shared_passenger,
                    "seat": "",
                    "cabin_class": "",
                    "departure_terminal": "",
                    "arrival_terminal": "",
                    "departure_gate": "",
                    "arrival_gate": "",
                }

                if (
                    flight_data["flight_number"]
                    and flight_data["departure_airport"]
                    and flight_data["arrival_airport"]
                ):
                    flights_data.append(flight_data)

                current_dt = seg_arr_dt + timedelta(
                    minutes=seg["layover_after_minutes"]
                )
        else:
            if first_flight_num:
                fd = _make_latam_flight(
                    rule,
                    dep_date_str,
                    dep_time_str,
                    dep_airport,
                    arr_date_str,
                    arr_time_str,
                    arr_airport,
                    first_flight_num,
                    shared_booking,
                    shared_passenger,
                )
                if fd:
                    flights_data.append(fd)

    return flights_data


def _make_latam_flight(
    rule,
    dep_date_str,
    dep_time_str,
    dep_airport,
    arr_date_str,
    arr_time_str,
    arr_airport,
    flight_number,
    booking_ref,
    passenger,
) -> dict | None:
    """Helper to create a flight dict for a direct LATAM segment."""
    dep_date = parse_flight_date(dep_date_str)
    arr_date = parse_flight_date(arr_date_str) or dep_date
    if dep_date is None:
        return None

    try:
        dep_h, dep_m = map(int, dep_time_str.split(":"))
        dep_dt = _make_aware(
            datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m)
        )

        arr_h, arr_m = map(int, arr_time_str.split(":"))
        arr_dt = _make_aware(
            datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m)
        )
    except (ValueError, TypeError):
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


# ---------------------------------------------------------------------------
# SAS custom extractor
# ---------------------------------------------------------------------------

# Well-known airport name → IATA mappings used by SAS/Amadeus e-tickets.
_SAS_KNOWN_AIRPORTS: dict[str, str] = {
    "stockholm arlanda": "ARN",
    "london heathrow": "LHR",
    "london gatwick": "LGW",
    "london city": "LCY",
    "london stansted": "STN",
    "london luton": "LTN",
    "paris charles de gaulle": "CDG",
    "paris orly": "ORY",
    "copenhagen kastrup": "CPH",
    "oslo gardermoen": "OSL",
    "gothenburg landvetter": "GOT",
    "bergen flesland": "BGO",
    "helsinki vantaa": "HEL",
    "amsterdam schiphol": "AMS",
    "frankfurt": "FRA",
    "munich": "MUC",
    "zurich": "ZRH",
    "brussels": "BRU",
    "vienna": "VIE",
    "lisbon": "LIS",
    "dublin": "DUB",
    "madrid": "MAD",
    "barcelona": "BCN",
    "rome fiumicino": "FCO",
    "milan malpensa": "MXP",
    "new york jfk": "JFK",
    "new york newark": "EWR",
    "los angeles": "LAX",
    "chicago": "ORD",
    "cape town": "CPT",
    "johannesburg": "JNB",
    "tokyo narita": "NRT",
    "tokyo haneda": "HND",
    "bangkok": "BKK",
    "singapore": "SIN",
    "hong kong": "HKG",
    "shanghai pudong": "PVG",
    "beijing": "PEK",
    "dubai": "DXB",
    "doha": "DOH",
    "istanbul": "IST",
    "arlanda": "ARN",
    "heathrow": "LHR",
    "gatwick": "LGW",
    "kastrup": "CPH",
    "gardermoen": "OSL",
    "landvetter": "GOT",
    "schiphol": "AMS",
    "fiumicino": "FCO",
    "malpensa": "MXP",
    # Oslo airport (Norwegian)
    "oslo airport": "OSL",
    "oslo lufthavn": "OSL",
}


def _extract_airports_from_sas_route(route_text: str) -> tuple[str, str]:
    """Extract departure and arrival IATA codes from a SAS PDF route string."""
    parts = re.split(r"\s+-\s+", route_text, maxsplit=1)
    if len(parts) != 2:
        return ("", "")
    dep_code = _resolve_sas_airport(parts[0].strip())
    arr_code = _resolve_sas_airport(parts[1].strip())
    return (dep_code, arr_code)


def _resolve_sas_airport(text: str) -> str:
    """Resolve IATA code from a SAS PDF airport/city string."""
    m = re.search(r"\b([A-Z]{3})$", text)
    if m:
        return m.group(1)

    name_lower = text.lower().strip()

    if name_lower in _SAS_KNOWN_AIRPORTS:
        return _SAS_KNOWN_AIRPORTS[name_lower]

    words = text.split()
    if words:
        last_word = words[-1].lower()
        if last_word in _SAS_KNOWN_AIRPORTS:
            return _SAS_KNOWN_AIRPORTS[last_word]

    # DB fallback: try airports table
    try:
        from ..database import db_conn

        with db_conn() as conn:
            if len(words) > 1:
                row = conn.execute(
                    "SELECT iata_code FROM airports WHERE name LIKE ? LIMIT 1",
                    (f"%{words[-1]}%",),
                ).fetchone()
                if row:
                    return row["iata_code"]
            row = conn.execute(
                "SELECT iata_code FROM airports WHERE name LIKE ? OR city_name LIKE ? LIMIT 1",
                (f"%{name_lower}%", f"%{name_lower}%"),
            ).fetchone()
            if row:
                return row["iata_code"]
    except Exception:
        pass

    return ""


def _extract_sas_flights(email_msg: EmailMessage, rule) -> list[dict]:
    """Custom SAS extractor. Supports block-style (Din resa) and PDF tabular formats."""
    body = email_msg.body
    flights_data: list[dict] = []

    booking_match = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|Buchungscode|confirmation\s*code)[:\s\[]+([A-Z0-9]{5,8})",
        email_msg.subject + "\n" + body,
        re.IGNORECASE,
    )
    shared_booking = booking_match.group(1).strip() if booking_match else ""

    shared_passenger = ""
    passenger_match = re.search(
        r"(?:Mr|Mrs|Ms|Miss)\s+([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)\s+Date\s+of\s+Issue",
        body,
        re.IGNORECASE,
    )
    if passenger_match:
        shared_passenger = passenger_match.group(1).strip()

    # Try PDF tabular format first
    pdf_line_re = re.compile(
        r"(?P<flight_number>(?:SK|DY|D8|VS|LH|LX|OS|TP|A3|SN|BA|AF)\s*\d{2,5})"
        r"\s*/\s*"
        r"(?P<day>\d{1,2})(?P<month>[A-Z]{3})"
        r"\s+"
        r"(?P<route>.+?)"
        r"\s+"
        r"(?P<dep_time>\d{1,2}:\d{2})"
        r"\s+"
        r"(?P<arr_time>\d{1,2}:\d{2})"
        r"(?:\s+\d{1,2}:\d{2})?"
        r"(?:\s+Terminal\s+(?P<terminal>\S+))?",
        re.IGNORECASE,
    )

    pdf_matches = list(pdf_line_re.finditer(body))
    if pdf_matches:
        ref_year = email_msg.date.year if email_msg.date else datetime.now().year

        for m in pdf_matches:
            flight_number = m.group("flight_number").strip().replace(" ", "")
            day = int(m.group("day"))
            month_str = m.group("month").upper()
            route_text = m.group("route").strip()
            dep_time_str = m.group("dep_time")
            arr_time_str = m.group("arr_time")
            terminal = m.group("terminal") or ""

            month_num = MONTH_MAP.get(month_str.lower())
            if not month_num:
                continue

            try:
                flight_date = date_type(ref_year, month_num, day)
            except ValueError:
                continue
            if email_msg.date and flight_date < email_msg.date.date():
                try:
                    flight_date = date_type(ref_year + 1, month_num, day)
                except ValueError:
                    continue

            dep_airport, arr_airport = _extract_airports_from_sas_route(route_text)
            if not dep_airport or not arr_airport:
                continue

            dep_h, dep_m_val = map(int, dep_time_str.split(":"))
            arr_h, arr_m_val = map(int, arr_time_str.split(":"))

            dep_dt = _make_aware(
                datetime(
                    flight_date.year,
                    flight_date.month,
                    flight_date.day,
                    dep_h,
                    dep_m_val,
                )
            )

            arr_date = flight_date
            if arr_h < dep_h or (arr_h == dep_h and arr_m_val < dep_m_val):
                arr_date = flight_date + timedelta(days=1)

            arr_dt = _make_aware(
                datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val)
            )

            flights_data.append(
                {
                    "airline_name": rule.airline_name,
                    "airline_code": rule.airline_code,
                    "flight_number": flight_number,
                    "departure_airport": dep_airport,
                    "arrival_airport": arr_airport,
                    "departure_datetime": dep_dt,
                    "arrival_datetime": arr_dt,
                    "booking_reference": shared_booking,
                    "passenger_name": shared_passenger,
                    "seat": "",
                    "cabin_class": "",
                    "departure_terminal": terminal,
                    "arrival_terminal": "",
                    "departure_gate": "",
                    "arrival_gate": "",
                }
            )

        if flights_data:
            return flights_data

    # Block-style fallback (Din resa / HTML-to-text)
    date_re = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")
    route_re = re.compile(
        r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})"
    )
    time_re = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    flight_num_re = re.compile(r"((?:SK|DY|D8|VS|LH|LX|OS|TP|A3|SN|BA|AF)\s*\d{2,5})")

    date_matches = list(date_re.finditer(body))

    for i, date_m in enumerate(date_matches):
        dep_date = parse_flight_date(date_m.group(1))
        if not dep_date:
            continue

        block_start = date_m.start()
        block_end = (
            date_matches[i + 1].start() if i + 1 < len(date_matches) else len(body)
        )
        block = body[block_start:block_end]

        routes = list(route_re.finditer(block))
        times = list(time_re.finditer(block))
        fns = list(flight_num_re.finditer(block))

        for j in range(min(len(routes), len(times), len(fns))):
            dep_airport = routes[j].group(1)
            arr_airport = routes[j].group(2)
            dep_time_str = times[j].group(1)
            arr_time_str = times[j].group(2)
            flight_number = fns[j].group(1).replace(" ", "")

            dep_h, dep_m_val = map(int, dep_time_str.split(":"))
            arr_h, arr_m_val = map(int, arr_time_str.split(":"))

            dep_dt = _make_aware(
                datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m_val)
            )

            arr_date = dep_date
            if arr_h < dep_h or (arr_h == dep_h and arr_m_val < dep_m_val):
                arr_date = dep_date + timedelta(days=1)

            arr_dt = _make_aware(
                datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m_val)
            )

            flight_data = {
                "airline_name": rule.airline_name,
                "airline_code": rule.airline_code,
                "flight_number": flight_number,
                "departure_airport": dep_airport,
                "arrival_airport": arr_airport,
                "departure_datetime": dep_dt,
                "arrival_datetime": arr_dt,
                "booking_reference": shared_booking,
                "passenger_name": "",
                "seat": "",
                "cabin_class": "",
                "departure_terminal": "",
                "arrival_terminal": "",
                "departure_gate": "",
                "arrival_gate": "",
            }

            if (
                flight_data["flight_number"]
                and flight_data["departure_airport"]
                and flight_data["arrival_airport"]
            ):
                flights_data.append(flight_data)

    return flights_data


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------


def extract_flights_from_email(email_msg: EmailMessage, rule) -> list[dict]:
    """
    Apply a rule to an email and extract flight data as a list of dicts.

    Tries BS4 (HTML) extraction first, then dispatches to custom extractors,
    then falls back to generic regex body_pattern matching.
    """
    # Try BS4 extraction first if HTML body is available
    if email_msg.html_body:
        from .bs4_extractors import extract_with_bs4

        bs4_result = extract_with_bs4(email_msg.html_body, rule, email_msg)
        if bs4_result:
            return bs4_result

    # Dispatch to custom extractors (regex-based fallback)
    extractor = getattr(rule, "custom_extractor", "")
    if extractor == "latam":
        return _extract_latam_flights(email_msg, rule)
    elif extractor in ("sas", "norwegian"):
        return _extract_sas_flights(email_msg, rule)

    # Generic regex body_pattern matching
    flights_data = []
    body = email_msg.body

    shared_booking = ""
    booking_match = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|Buchungscode|Buchungsnummer|reservation\s*code|"
        r"confirmation\s*code|Reservierungscode)[:\s\[]+([A-Z0-9]{5,8})",
        email_msg.subject + "\n" + body,
        re.IGNORECASE,
    )
    if booking_match:
        shared_booking = booking_match.group(1).strip()

    shared_passenger = ""
    passenger_match = re.search(
        r"(?:Lista\s+de\s+passageiros|passenger\s*(?:list|name)|"
        r"Passagier|Reisender|passager|passasjer)"
        r"[\s:]*\n\s*(?:[-•·]\s*)?"
        r"([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:[ ]+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)+)",
        body,
        re.IGNORECASE,
    )
    if passenger_match:
        shared_passenger = passenger_match.group(1).strip()

    try:
        matches = list(re.finditer(rule.body_pattern, body, re.IGNORECASE | re.DOTALL))
        if not matches:
            logger.debug(
                "No body_pattern matches for rule '%s' in email %s",
                rule.airline_name,
                email_msg.message_id,
            )
            return flights_data

        for match in matches:
            groups = match.groupdict()
            raw_flight_num = groups.get("flight_number", "").strip()
            if raw_flight_num and raw_flight_num.isdigit() and rule.airline_code:
                raw_flight_num = f"{rule.airline_code}{raw_flight_num}"

            flight_data = {
                "airline_name": rule.airline_name,
                "airline_code": rule.airline_code,
                "flight_number": raw_flight_num,
                "departure_airport": groups.get("departure_airport", "")
                .strip()
                .upper(),
                "arrival_airport": groups.get("arrival_airport", "").strip().upper(),
                "booking_reference": groups.get("booking_reference", "").strip()
                or shared_booking,
                "passenger_name": groups.get("passenger_name", "").strip()
                or shared_passenger,
                "seat": groups.get("seat", "").strip(),
                "cabin_class": groups.get("cabin_class", "").strip().lower(),
                "departure_terminal": groups.get("departure_terminal", "").strip(),
                "arrival_terminal": groups.get("arrival_terminal", "").strip(),
                "departure_gate": groups.get("departure_gate", "").strip(),
                "arrival_gate": groups.get("arrival_gate", "").strip(),
            }

            dep_date_str = groups.get("departure_date", "").strip()
            dep_time_str = groups.get("departure_time", "").strip()

            if not dep_date_str:
                _ctx_date_re = r"(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})"
                _ctx_dates = list(re.finditer(_ctx_date_re, body[: match.start()]))
                if _ctx_dates:
                    dep_date_str = _ctx_dates[-1].group(1)

            arr_date_str = groups.get("arrival_date", "").strip() or dep_date_str
            arr_time_str = groups.get("arrival_time", "").strip()

            ref_year = email_msg.date.year if email_msg.date else datetime.now().year

            dep_date = parse_flight_date(dep_date_str)
            if dep_date is None and dep_date_str:
                try:
                    dep_date = datetime.strptime(dep_date_str, rule.date_format).date()
                except (ValueError, TypeError):
                    pass
            if dep_date is not None and dep_date.year == 1900:
                candidate = dep_date.replace(year=ref_year)
                if email_msg.date and candidate < email_msg.date.date():
                    candidate = dep_date.replace(year=ref_year + 1)
                dep_date = candidate
            if dep_date is None or not dep_time_str:
                logger.warning(
                    "Cannot parse departure datetime: %r %r", dep_date_str, dep_time_str
                )
                continue

            try:
                h, m = dep_time_str.split(":")
                dep_dt = datetime(
                    dep_date.year, dep_date.month, dep_date.day, int(h), int(m)
                )
                flight_data["departure_datetime"] = _make_aware(dep_dt)
            except (ValueError, TypeError) as e:
                logger.warning("Bad departure time %r: %s", dep_time_str, e)
                continue

            arr_date = parse_flight_date(arr_date_str)
            if arr_date is None and arr_date_str:
                try:
                    arr_date = datetime.strptime(arr_date_str, rule.date_format).date()
                except (ValueError, TypeError):
                    pass
            if arr_date is not None and arr_date.year == 1900:
                candidate = arr_date.replace(year=ref_year)
                if email_msg.date and candidate < email_msg.date.date():
                    candidate = arr_date.replace(year=ref_year + 1)
                arr_date = candidate
            if arr_date is None:
                arr_date = dep_date

            if arr_time_str:
                try:
                    h, m = arr_time_str.split(":")
                    arr_dt = datetime(
                        arr_date.year, arr_date.month, arr_date.day, int(h), int(m)
                    )
                    flight_data["arrival_datetime"] = _make_aware(arr_dt)
                except (ValueError, TypeError) as e:
                    logger.warning("Bad arrival time %r: %s", arr_time_str, e)
                    continue
            else:
                logger.warning("No arrival time found, skipping")
                continue

            # Normalise cabin class
            cabin_map = {
                "economy": "economy",
                "eco": "economy",
                "y": "economy",
                "premium economy": "premium_economy",
                "premium": "premium_economy",
                "w": "premium_economy",
                "business": "business",
                "j": "business",
                "c": "business",
                "first": "first",
                "f": "first",
                "econômica": "economy",
                "económica": "economy",
                "ejecutiva": "business",
            }
            raw_cabin = flight_data.get("cabin_class", "")
            flight_data["cabin_class"] = cabin_map.get(raw_cabin, "")

            if (
                flight_data["flight_number"]
                and flight_data["departure_airport"]
                and flight_data["arrival_airport"]
            ):
                flights_data.append(flight_data)
            else:
                logger.debug("Skipping incomplete flight match: %s", flight_data)

    except re.error as e:
        logger.error("Regex error in rule %s body_pattern: %s", rule.airline_name, e)

    return flights_data


def get_rules():
    """Return all active built-in rules sorted by priority."""
    return sorted(get_builtin_rules(), key=lambda r: (-r.priority, r.airline_name))
