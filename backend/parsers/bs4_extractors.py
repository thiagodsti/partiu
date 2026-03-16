"""
BeautifulSoup-based flight data extraction from HTML emails.

Uses semantic markers and DOM structure to extract flight data — more robust
than regex on flattened text because it leverages the HTML hierarchy.

Adapted from AdventureLog — Django dependencies removed.
Norwegian Air Shuttle extractor delegates to SAS extractor (similar format).
"""

import logging
import re
from datetime import datetime, date as date_type, timedelta, timezone

from bs4 import BeautifulSoup

from .engine import parse_flight_date, MONTH_MAP  # noqa: F401 (re-exported for convenience)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _get_text(soup_or_tag) -> str:
    """Get clean text from a BS4 element, collapsing whitespace."""
    if soup_or_tag is None:
        return ''
    text = soup_or_tag.get_text(separator=' ', strip=True)
    return re.sub(r'\s+', ' ', text).strip()


def _find_by_text(soup, pattern, tag=None):
    """Find elements whose text matches a regex pattern."""
    compiled = re.compile(pattern, re.IGNORECASE)
    if tag:
        return soup.find_all(tag, string=compiled)
    return soup.find_all(string=compiled)


def _extract_airports(text: str) -> list[str]:
    """Extract all 3-letter IATA airport codes in parentheses from text."""
    return re.findall(r'\(([A-Z]{3})\)', text)


def _extract_bare_airports(text: str) -> list[str]:
    """Extract standalone 3-letter codes (on their own or in parentheses)."""
    parens = re.findall(r'\(([A-Z]{3})\)', text)
    if parens:
        return parens
    return re.findall(r'(?:^|\s)([A-Z]{3})(?:\s|$)', text)


def _extract_time(text: str) -> str | None:
    """Extract HH:MM time from text."""
    m = re.search(r'(\d{1,2}:\d{2})', text)
    return m.group(1) if m else None


def _extract_times(text: str) -> list[str]:
    """Extract all HH:MM times from text."""
    return re.findall(r'\d{1,2}:\d{2}', text)


def _extract_flight_number(text: str, airline_codes: list[str] | None = None) -> str | None:
    """Extract a flight number like 'LA 1234' or 'SK1829' from text."""
    if airline_codes:
        codes = '|'.join(re.escape(c) for c in airline_codes)
        m = re.search(rf'({codes})\s*(\d{{2,5}})', text)
        if m:
            return f"{m.group(1)}{m.group(2)}"
    m = re.search(r'([A-Z]{2})\s*(\d{2,5})', text)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return None


def _make_aware_dt(dt: datetime) -> datetime:
    """Make a naive datetime timezone-aware (UTC)."""
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def _build_datetime(date_obj: date_type, time_str: str) -> datetime | None:
    """Combine a date and HH:MM string into a timezone-aware datetime."""
    if not date_obj or not time_str:
        return None
    try:
        h, m = map(int, time_str.split(':'))
        return _make_aware_dt(datetime(date_obj.year, date_obj.month, date_obj.day, h, m))
    except (ValueError, TypeError):
        return None


def _estimate_block_time_minutes(iata_a: str, iata_b: str) -> float:
    """
    Estimate scheduled block time (minutes) between two airports using
    great-circle distance + a cruise-speed model calibrated against real routes.

    Model: block_time = overhead + dist_km / cruise_speed_kmh * 60
    Overhead and cruise speed vary by distance band (climb/descent fraction is
    larger for short routes, jets run faster cruise for very long hauls).
    """
    dist_km = _airport_distance(iata_a, iata_b)
    if dist_km <= 0:
        return 90.0  # safe fallback

    if dist_km < 1000:       # e.g. MXP→FRA ~850 km
        overhead, speed = 25, 850
    elif dist_km < 3000:     # e.g. ARN→FRA ~1700 km
        overhead, speed = 35, 870
    elif dist_km < 7000:     # medium long-haul
        overhead, speed = 50, 890
    else:                    # e.g. FRA→GRU ~9900 km, GRU→MXP ~9700 km
        overhead, speed = 60, 920

    return overhead + dist_km / speed * 60


def _airport_distance(iata_a: str, iata_b: str) -> float:
    """Return approximate great-circle distance in km between two airports. Falls back to 1.0."""
    import math
    try:
        from ..database import db_conn
        with db_conn() as conn:
            rows = {r['iata_code']: r for r in conn.execute(
                'SELECT iata_code, latitude, longitude FROM airports WHERE iata_code IN (?, ?)',
                (iata_a.upper(), iata_b.upper()),
            ).fetchall()}
        a, b = rows.get(iata_a.upper()), rows.get(iata_b.upper())
        if not a or not b or a['latitude'] is None or b['latitude'] is None:
            return 1.0
        lat1, lon1 = math.radians(a['latitude']), math.radians(a['longitude'])
        lat2, lon2 = math.radians(b['latitude']), math.radians(b['longitude'])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371 * 2 * math.asin(math.sqrt(h))
    except Exception:
        return 1.0


def _extract_booking_reference(soup, subject: str = '') -> str:
    """Extract booking reference using semantic markers."""
    full_text = subject + '\n' + _get_text(soup)
    m = re.search(
        r'(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|'
        r'Bokning|Reserva|PNR|Buchungscode|Buchungsnummer|'
        r'reservation\s*code|confirmation\s*code)[:\s\[]+([A-Z0-9]{5,8})',
        full_text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.search(r'Booking\s*:\s*([A-Z0-9]{5,8})', full_text, re.IGNORECASE)
    return m.group(1).strip() if m else ''


def _extract_passenger_name(soup) -> str:
    """Extract passenger name using semantic markers."""
    text = _get_text(soup)

    m = re.search(
        r'(?:Lista\s+de\s+passageiros|passenger\s*(?:list|name)|'
        r'Passagier|Reisender|passager|passasjer)'
        r'[\s:]*[-•·]?\s*'
        r'([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)',
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    m = re.search(
        r'(?:Ol[áa]|Hello|Hola)\s+(?:<b[^>]*>)?\s*([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)',
        text, re.IGNORECASE,
    )
    return m.group(1).strip() if m else ''


def _make_flight_dict(
    rule, flight_number, dep_airport, arr_airport,
    dep_dt, arr_dt, booking_ref='', passenger='',
) -> dict | None:
    """Create a flight data dict if all required fields are present."""
    if not all([flight_number, dep_airport, arr_airport, dep_dt, arr_dt]):
        return None
    return {
        'airline_name': rule.airline_name,
        'airline_code': rule.airline_code,
        'flight_number': flight_number,
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
    }


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def extract_with_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Try BS4 extraction. Returns [] if extraction not possible or fails,
    signaling the caller to fall back to regex.
    """
    if not html or not html.strip():
        return []

    extractor_name = getattr(rule, 'custom_extractor', '')
    extractors = {
        'latam': _extract_latam_bs4,
        'sas': _extract_sas_bs4,
        'norwegian': _extract_norwegian_bs4,
        'lufthansa': _extract_lufthansa_bs4,
        'azul': _extract_azul_bs4,
    }

    extractor = extractors.get(extractor_name)
    if not extractor:
        return []

    try:
        result = extractor(html, rule, email_msg)
        if result:
            logger.debug(
                "BS4 extractor '%s' found %d flight(s)", extractor_name, len(result)
            )
        return result
    except Exception:
        logger.debug(
            "BS4 extractor '%s' failed, falling back to regex", extractor_name, exc_info=True
        )
        return []


# ---------------------------------------------------------------------------
# LATAM Airlines
# ---------------------------------------------------------------------------

def _extract_latam_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Extract flights from LATAM HTML emails.
    Also searches PDF attachment text for segment times not present in the HTML.
    """
    soup = BeautifulSoup(html, 'lxml')
    html_text = _get_text(soup)

    # Append PDF attachment text — LATAM often attaches a full itinerary PDF
    # with individual segment departure/arrival times not in the HTML.
    pdf_text = ''
    if hasattr(email_msg, 'get_pdf_text'):
        pdf_text = email_msg.get_pdf_text()
    elif hasattr(email_msg, 'pdf_attachments') and email_msg.pdf_attachments:
        from ..parsers.email_connector import _extract_text_from_pdf
        for b in email_msg.pdf_attachments:
            t = _extract_text_from_pdf(b)
            if t:
                pdf_text += '\n' + t

    # Also check body (may contain pre-extracted PDF text from cache)
    body_extra = ''
    if email_msg.body and len(email_msg.body) > len(html_text):
        body_extra = email_msg.body

    # Prefer PDF text for segment matching; fall back to HTML then body
    text = html_text
    if pdf_text:
        text = html_text + '\n\n--- PDF ---\n' + pdf_text
    elif body_extra:
        text = html_text + '\n\n' + body_extra

    # Pre-parse PDF segment table (DD/MM/YY format) for accurate per-leg times
    pdf_segments = _parse_latam_pdf_segments(pdf_text) if pdf_text else {}

    flights = []

    booking_ref = _extract_booking_reference(soup, email_msg.subject)
    passenger = _extract_passenger_name(soup)

    _DATE_RE = r'(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})'
    _TIME_RE = r'(\d{1,2}:\d{2})'
    _AIRPORT_RE = r'\(([A-Z]{3})\)'
    _FLIGHT_NUM_RE = r'([A-Z0-9]{2}\s*\d{3,5})(?!\w)'

    direction_splits = re.split(
        r'(Voo de (?:ida|volta)|(?:Outbound|Return|Inbound)\s+(?:flight|journey))',
        text, flags=re.IGNORECASE,
    )

    sections = []
    if len(direction_splits) <= 1:
        trecho_splits = re.split(r'Trecho\s+\d+', text, flags=re.IGNORECASE)
        if len(trecho_splits) > 1:
            sections = trecho_splits[1:]
        else:
            sections = [text]
    else:
        i = 1
        while i < len(direction_splits):
            content = direction_splits[i + 1] if i + 1 < len(direction_splits) else ''
            sections.append(direction_splits[i] + content)
            i += 2

    for section in sections:
        segment_matches = list(re.finditer(
            _DATE_RE + r'\s+' + _TIME_RE + r'.*?' + _AIRPORT_RE,
            section, re.DOTALL,
        ))

        flight_nums = re.findall(_FLIGHT_NUM_RE, section)

        if len(segment_matches) >= 2 and flight_nums:
            connections = list(re.finditer(
                r'Troca\s+de\s+avi[ãa]o\s+em:.*?\(([A-Z]{3})\)\s+'
                r'([A-Z0-9]{2}\s*\d{3,5}).*?'
                r'Tempo\s+de\s+espera:\s*(\d+)\s*hr?\s*(\d+)\s*min',
                section, re.DOTALL | re.IGNORECASE,
            ))

            if connections:
                dep_match = segment_matches[0]
                arr_match = segment_matches[-1]

                dep_airport = dep_match.group(3)
                arr_airport = arr_match.group(3)
                first_flight = flight_nums[0].strip() if flight_nums else ''

                segments = []
                prev_airport = dep_airport
                for conn in connections:
                    conn_airport = conn.group(1)
                    conn_flight = conn.group(2).strip()
                    layover_min = int(conn.group(3)) * 60 + int(conn.group(4))
                    segments.append({
                        'dep_airport': prev_airport,
                        'arr_airport': conn_airport,
                        'flight_number': first_flight if not segments else segments[-1].get('next_flight', conn_flight),
                        'layover_minutes': layover_min,
                        'next_flight': conn_flight,
                    })
                    prev_airport = conn_airport
                segments.append({
                    'dep_airport': prev_airport,
                    'arr_airport': arr_airport,
                    'flight_number': segments[-1]['next_flight'] if segments else first_flight,
                    'layover_minutes': 0,
                })

                n_segments = len(segments)

                # Prefer reading explicit dep/arr times for each segment directly from the
                # email (2 matches per segment: departure + arrival).
                if len(segment_matches) >= 2 * n_segments:
                    for idx, seg in enumerate(segments):
                        dep_m = segment_matches[idx * 2]
                        arr_m = segment_matches[idx * 2 + 1]
                        dep_date = parse_flight_date(dep_m.group(1))
                        arr_date = parse_flight_date(arr_m.group(1))
                        if not dep_date or not arr_date:
                            continue
                        seg_dep_dt = _build_datetime(dep_date, dep_m.group(2))
                        seg_arr_dt = _build_datetime(arr_date, arr_m.group(2))
                        flight = _make_flight_dict(
                            rule, seg['flight_number'], seg['dep_airport'], seg['arr_airport'],
                            seg_dep_dt, seg_arr_dt, booking_ref, passenger,
                        )
                        if flight:
                            flights.append(flight)
                else:
                    # Attempt 2: use exact segment times from the PDF itinerary attachment.
                    # The LATAM PDF uses DD/MM/YY HH:MM local times — same handling as HTML.
                    if pdf_segments:
                        pdf_flights = []
                        for seg in segments:
                            fn = seg['flight_number'].replace(' ', '')
                            if fn not in pdf_segments:
                                pdf_flights = []
                                break
                            dep_ds, dep_ts, arr_ds, arr_ts = pdf_segments[fn]
                            seg_dep_date = _parse_ddmmyy_date(dep_ds)
                            seg_arr_date = _parse_ddmmyy_date(arr_ds)
                            if not seg_dep_date or not seg_arr_date:
                                pdf_flights = []
                                break
                            seg_dep_dt = _build_datetime(seg_dep_date, dep_ts)
                            seg_arr_dt = _build_datetime(seg_arr_date, arr_ts)
                            flight = _make_flight_dict(
                                rule, seg['flight_number'], seg['dep_airport'], seg['arr_airport'],
                                seg_dep_dt, seg_arr_dt, booking_ref, passenger,
                            )
                            if flight:
                                pdf_flights.append(flight)
                        if pdf_flights and len(pdf_flights) == len(segments):
                            logger.debug(
                                "Used PDF segment times for %d flights",
                                len(pdf_flights),
                            )
                            flights.extend(pdf_flights)
                            continue  # skip proportional fallback

                    # Attempt 3: distribute proportionally by great-circle distance.
                    # We convert dep/arr to real UTC first so total_elapsed is accurate
                    # across timezone boundaries (e.g. ARN→GRU spans UTC+1 → UTC-3).
                    dep_date = parse_flight_date(dep_match.group(1))
                    arr_date = parse_flight_date(arr_match.group(1))
                    if not dep_date or not arr_date:
                        continue
                    dep_dt = _build_datetime(dep_date, dep_match.group(2))
                    arr_dt = _build_datetime(arr_date, arr_match.group(2))
                    if not dep_dt or not arr_dt:
                        continue

                    # Convert local-labeled-as-UTC times to actual UTC
                    try:
                        from ..timezone_utils import localize_to_utc as _ltu
                        dep_airport_code = dep_match.group(3)
                        arr_airport_code = arr_match.group(3)
                        dep_utc = _ltu(dep_dt.replace(tzinfo=None), dep_airport_code)
                        arr_utc = _ltu(arr_dt.replace(tzinfo=None), arr_airport_code)
                    except Exception:
                        dep_utc = dep_dt
                        arr_utc = arr_dt

                    total_elapsed = (arr_utc - dep_utc).total_seconds()
                    total_layover = sum(s['layover_minutes'] * 60 for s in segments)
                    total_flight = total_elapsed - total_layover
                    if total_flight <= 0:
                        continue

                    distances = [_airport_distance(s['dep_airport'], s['arr_airport']) for s in segments]
                    total_dist = sum(distances) or 1
                    current_dt = dep_utc  # work in actual UTC
                    for seg, dist in zip(segments, distances):
                        seg_dep_dt = current_dt
                        seg_flight_sec = total_flight * (dist / total_dist)
                        seg_arr_dt = seg_dep_dt + timedelta(seconds=seg_flight_sec)
                        flight = _make_flight_dict(
                            rule, seg['flight_number'], seg['dep_airport'], seg['arr_airport'],
                            seg_dep_dt, seg_arr_dt, booking_ref, passenger,
                        )
                        if flight:
                            # Times are already correct UTC — skip re-conversion in apply_airport_timezones
                            flight['_times_already_utc'] = True
                            flights.append(flight)
                        current_dt = seg_arr_dt + timedelta(minutes=seg['layover_minutes'])
            else:
                for i in range(0, len(segment_matches) - 1, 2):
                    dep_m = segment_matches[i]
                    arr_m = segment_matches[i + 1]

                    dep_date = parse_flight_date(dep_m.group(1))
                    arr_date = parse_flight_date(arr_m.group(1))
                    if not dep_date or not arr_date:
                        continue

                    dep_dt = _build_datetime(dep_date, dep_m.group(2))
                    arr_dt = _build_datetime(arr_date, arr_m.group(2))

                    fn_idx = i // 2
                    fn = flight_nums[fn_idx].strip() if fn_idx < len(flight_nums) else ''

                    flight = _make_flight_dict(
                        rule, fn, dep_m.group(3), arr_m.group(3),
                        dep_dt, arr_dt, booking_ref, passenger,
                    )
                    if flight:
                        flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# SAS Scandinavian Airlines
# ---------------------------------------------------------------------------

def _extract_sas_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Extract flights from SAS HTML emails.
    Also used for Norwegian (similar HTML structure).
    """
    soup = BeautifulSoup(html, 'lxml')
    text = _get_text(soup)
    flights = []

    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    date_re = re.compile(r'(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)')
    route_re = re.compile(r'([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})')
    time_re = re.compile(r'(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})')
    # Include DY/D8 for Norwegian
    flight_num_re = re.compile(
        r'((?:SK|DY|D8|VS|LH|LX|OS|TP|A3|SN|BA|AF)\s*\d{2,5})'
    )

    date_matches = list(date_re.finditer(text))

    for i, date_m in enumerate(date_matches):
        dep_date = parse_flight_date(date_m.group(1))
        if not dep_date:
            continue

        block_start = date_m.start()
        block_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(text)
        block = text[block_start:block_end]

        route_m = route_re.search(block)
        time_m = time_re.search(block)
        fn_m = flight_num_re.search(block)

        if not all([route_m, time_m, fn_m]):
            continue

        dep_airport = route_m.group(1)
        arr_airport = route_m.group(2)
        dep_time = time_m.group(1)
        arr_time = time_m.group(2)
        flight_number = fn_m.group(1).replace(' ', '')

        dep_dt = _build_datetime(dep_date, dep_time)
        arr_dt = _build_datetime(dep_date, arr_time)

        # Handle overnight flights
        if arr_dt and dep_dt and arr_dt < dep_dt:
            arr_dt = _build_datetime(
                date_type(dep_date.year, dep_date.month, dep_date.day) + timedelta(days=1),
                arr_time,
            )

        flight = _make_flight_dict(
            rule, flight_number, dep_airport, arr_airport,
            dep_dt, arr_dt, booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Norwegian Air Shuttle
# ---------------------------------------------------------------------------

def _extract_norwegian_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Extract flights from Norwegian HTML emails.
    Delegates to the SAS extractor since the HTML structure is similar.
    """
    return _extract_sas_bs4(html, rule, email_msg)


# ---------------------------------------------------------------------------
# Lufthansa
# ---------------------------------------------------------------------------

def _extract_lufthansa_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Extract flights from Lufthansa HTML emails.
    """
    soup = BeautifulSoup(html, 'lxml')
    text = _get_text(soup)
    flights = []

    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    _DATE = r'(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})'
    _TIME = r'(\d{1,2}:\d{2})'
    _AIRPORT = r'\(([A-Z]{3})\)'

    dta_pattern = re.compile(
        _DATE + r'\s+' + _TIME + r'.*?' + _AIRPORT,
        re.DOTALL,
    )
    matches = list(dta_pattern.finditer(text))

    fn_pattern = re.compile(r'(LH\s*\d{3,5})')
    fn_matches = list(fn_pattern.finditer(text))

    for i in range(0, len(matches) - 1, 2):
        dep_m = matches[i]
        arr_m = matches[i + 1]

        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue

        dep_dt = _build_datetime(dep_date, dep_m.group(2))
        arr_dt = _build_datetime(arr_date, arr_m.group(2))

        flight_number = ''
        for fn_m in fn_matches:
            if dep_m.start() <= fn_m.start() <= arr_m.start():
                flight_number = fn_m.group(1).replace(' ', '')
                break

        flight = _make_flight_dict(
            rule, flight_number, dep_m.group(3), arr_m.group(3),
            dep_dt, arr_dt, booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Azul Brazilian Airlines
# ---------------------------------------------------------------------------

def _extract_azul_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Extract flights from Azul HTML emails.
    """
    soup = BeautifulSoup(html, 'lxml')
    flights = []

    booking_ref = _extract_booking_reference(soup, email_msg.subject)

    ref_year = email_msg.date.year if email_msg.date else datetime.now().year

    text = _get_text(soup)

    block_re = re.compile(
        r'(?:^|\s)([A-Z]{3})\s'
        r'.*?'
        r'(\d{2}/\d{2})\s*[•·]\s*'
        r'(\d{1,2}:\d{2})'
        r'.*?'
        r'(?:Voo|Flight)\s+(\d{3,5})'
        r'.*?'
        r'(?:^|\s)([A-Z]{3})\s'
        r'.*?'
        r'(\d{2}/\d{2})\s*[•·]\s*'
        r'(\d{1,2}:\d{2})',
        re.DOTALL | re.MULTILINE,
    )

    for m in block_re.finditer(text):
        dep_airport = m.group(1)
        dep_date_str = m.group(2)
        dep_time = m.group(3)
        flight_num_raw = m.group(4)
        arr_airport = m.group(5)
        arr_date_str = m.group(6)
        arr_time = m.group(7)

        dep_date = _parse_ddmm_date(dep_date_str, ref_year, email_msg.date)
        arr_date = _parse_ddmm_date(arr_date_str, ref_year, email_msg.date)
        if not dep_date or not arr_date:
            continue

        dep_dt = _build_datetime(dep_date, dep_time)
        arr_dt = _build_datetime(arr_date, arr_time)

        flight_number = f"{rule.airline_code}{flight_num_raw}"

        flight = _make_flight_dict(
            rule, flight_number, dep_airport, arr_airport,
            dep_dt, arr_dt, booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


def _parse_ddmm_date(date_str: str, ref_year: int, email_date=None) -> date_type | None:
    """Parse a DD/MM date string and infer the year."""
    m = re.match(r'(\d{2})/(\d{2})', date_str)
    if not m:
        return None
    try:
        day, month = int(m.group(1)), int(m.group(2))
        candidate = date_type(ref_year, month, day)
        if email_date and candidate < email_date.date():
            candidate = date_type(ref_year + 1, month, day)
        return candidate
    except ValueError:
        return None


def _parse_ddmmyy_date(s: str) -> date_type | None:
    """Parse DD/MM/YY (2-digit year) date string, assuming 2000+ century."""
    parts = s.split('/')
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        return date_type(2000 + y, m, d)
    except (ValueError, TypeError):
        return None


def _parse_latam_pdf_segments(pdf_text: str) -> dict:
    """
    Parse LATAM PDF attachment itinerary table (DD/MM/YY HH:MM format).

    Returns dict mapping normalized flight number (no spaces) to
    (dep_date_str, dep_time_str, arr_date_str, arr_time_str).

    Example PDF line:
      LA8072 (Guarulhos (Malpensa 16/03/26 18:00 17/03/26 9:15 Economy Light
    """
    result = {}
    # Match: <flight_num> <non-digit non-newline content ≤60 chars> <DD/MM/YY HH:MM DD/MM/YY HH:MM>
    pattern = re.compile(
        r'\b([A-Z]{2}\s*\d{2,5})\b[^\d\n]{0,60}?'
        r'(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s+'
        r'(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})'
    )
    for m in pattern.finditer(pdf_text):
        fn = m.group(1).replace(' ', '')
        result[fn] = (m.group(2), m.group(3), m.group(4), m.group(5))
    if result:
        logger.debug("PDF segments parsed: %s", list(result.keys()))
    return result
