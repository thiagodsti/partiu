"""
LATAM Airlines flight extractor.

Two extraction strategies:
  1. extract_bs4()   — HTML email body parsed with BeautifulSoup.
                       Also reads PDF attachments for per-segment times.
  2. extract_regex() — plain-text fallback when HTML is unavailable.

Both strategies split the email into directional sections (outbound/return)
and handle direct and connecting flights with layovers.
"""

import logging
import re
from datetime import date as date_type
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _airport_distance,
    _build_datetime,
    _get_text,
    _make_aware,
    extract_booking_reference,
    extract_passenger,
    make_flight_dict,
)

logger = logging.getLogger(__name__)

# Regex building blocks reused across both extractors
_date_fragment = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
_time_fragment = r"(\d{1,2}:\d{2})"
_airport_fragment = r"\(([A-Z]{3})\)"
_flight_number_fragment = r"([A-Z0-9]{2}\s*\d{3,5})(?!\w)"

_segment_re = re.compile(
    _date_fragment + r"\s+" + _time_fragment + r".*?" + _airport_fragment,
    re.DOTALL,
)
_connection_re = re.compile(
    r"Troca\s+de\s+avi[ãa]o\s+em:.*?\(([A-Z]{3})\)\s+"
    r"([A-Z0-9]{2}\s*\d{3,5}).*?"
    r"(?:Tempo\s+de\s+espera|Layover):\s*(\d+)\s*hr?\s*(\d+)\s*min",
    re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Date helpers specific to LATAM
# ---------------------------------------------------------------------------


def _parse_ddmmyy(s: str) -> date_type | None:
    """Parse a DD/MM/YY date string (2-digit year, century assumed 2000+)."""
    parts = s.split("/")
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        return date_type(2000 + y, m, d)
    except (ValueError, TypeError):
        return None


def _parse_pdf_segments(pdf_text: str) -> dict[str, tuple]:
    """Parse the LATAM PDF itinerary table (DD/MM/YY HH:MM format).

    Returns a dict mapping normalised flight number to
    (dep_date_str, dep_time_str, arr_date_str, arr_time_str).
    """
    result = {}
    pattern = re.compile(
        r"\b([A-Z]{2}\s*\d{2,5})\b[^\d\n]{0,60}?"
        r"(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s+"
        r"(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})"
    )
    for m in pattern.finditer(pdf_text):
        fn = m.group(1).replace(" ", "")
        result[fn] = (m.group(2), m.group(3), m.group(4), m.group(5))
    return result


# ---------------------------------------------------------------------------
# Section splitting (shared by BS4 and regex extractors)
# ---------------------------------------------------------------------------


def _split_into_sections(text: str) -> list[str]:
    """Split itinerary text into one section per flight direction.

    Recognises PT ("Voo de ida/volta") and EN ("Outbound/Return flight")
    section markers. Returns [text] when none are found.
    """
    direction_splits = re.split(
        r"(Voo de (?:ida|volta)|(?:Outbound|Return|Inbound)\s+(?:flight|journey))",
        text,
        flags=re.IGNORECASE,
    )
    if len(direction_splits) > 1:
        sections = []
        i = 1
        while i < len(direction_splits):
            content = direction_splits[i + 1] if i + 1 < len(direction_splits) else ""
            sections.append(direction_splits[i] + content)
            i += 2
        return sections

    trecho_splits = re.split(r"Trecho\s+\d+", text, flags=re.IGNORECASE)
    if len(trecho_splits) > 1:
        return trecho_splits[1:]

    return [text]


# ---------------------------------------------------------------------------
# City-name itinerary ("Itinerário da viagem" / "Informação de voo")
# ---------------------------------------------------------------------------
# LATAM's purchase-confirmation and flight-information emails print the
# itinerary with *city names only* — no IATA code anywhere on the page:
#
#     24 de dez. de 2024      02 de fev. de 2024
#     8:00                    12:50
#     São Paulo               São Paulo
#     LA3300                  (LA3302)          ← parenthesised in some variants
#     24 de dez. de 2024      02 de fev. de 2024
#     9:15                    14:05
#     Florianópolis           Florianópolis
#
# Every other LATAM format anchors on "(GRU)"-style codes, so these emails fell
# through to the generic scanner, which only ever recovered the first leg of a
# round trip. The shape is rigid enough to read directly: a date/time/place
# triple, a flight number, then a second triple.

_city_time_re = re.compile(r"^(\d{1,2}:\d{2})$")
_city_flight_re = re.compile(r"^\(?([A-Z]{2}[\s\xa0]?\d{2,5})\)?$")
# A place line is free text; these are the labels that sit in the same column
# and must not be mistaken for a city.
_city_reject_re = re.compile(
    r"\d|^(?:voo|trecho|itiner|informa|tarifa|classe|dura|escala|conex|total|"
    r"passageir|reserva|status|assento)",
    re.IGNORECASE,
)


def _city_place_iata(line: str) -> str:
    """Resolve a city/airport name line to an IATA code ('' when implausible)."""
    from ..shared import is_valid_iata, resolve_iata

    s = line.strip()
    if not s or len(s) > 40 or _city_reject_re.search(s):
        return ""
    if len(s.split()) > 4:
        return ""
    code = resolve_iata(s)
    return code if code and is_valid_iata(code) else ""


def _extract_city_itinerary(text_nl: str, rule, booking_ref: str, passenger: str) -> list[dict]:
    """Read the city-name itinerary layout described above."""
    lines = [ln.strip() for ln in text_nl.split("\n") if ln.strip()]

    def triple(i: int) -> tuple[date_type, str, str, int] | None:
        """Match a date/time/place triple starting at line *i*."""
        if i + 2 >= len(lines):
            return None
        d = parse_flight_date(lines[i])
        if d is None:
            return None
        t = _city_time_re.match(lines[i + 1])
        if not t:
            return None
        code = _city_place_iata(lines[i + 2])
        if not code:
            return None
        return d, t.group(1), code, i + 3

    flights: list[dict] = []
    seen: set[tuple] = set()
    i = 0
    while i < len(lines):
        dep = triple(i)
        if dep is None:
            i += 1
            continue
        dep_date, dep_time, dep_iata, nxt = dep

        m = _city_flight_re.match(lines[nxt]) if nxt < len(lines) else None
        if not m:
            i = nxt
            continue

        arr = triple(nxt + 1)
        if arr is None:
            i = nxt + 1
            continue
        arr_date, arr_time, arr_iata, after = arr

        if dep_iata == arr_iata:
            i = after
            continue

        dep_dt = _build_datetime(dep_date, dep_time)
        arr_dt = _build_datetime(arr_date, arr_time)
        if not dep_dt or not arr_dt:
            i = after
            continue

        fn = m.group(1).replace(" ", "").replace("\xa0", "")
        key = (fn, dep_iata, arr_iata)
        if key not in seen:
            seen.add(key)
            flight = make_flight_dict(
                rule, fn, dep_iata, arr_iata, dep_dt, arr_dt, booking_ref, passenger
            )
            if flight:
                flights.append(flight)
        i = after

    return flights


# ---------------------------------------------------------------------------
# BS4 extractor
# ---------------------------------------------------------------------------


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a LATAM HTML email.

    When no language-specific section headers are found, falls back to the
    generic flight-number-anchoring approach.
    """
    from ..shared import html_to_text

    soup = BeautifulSoup(html, "lxml")
    html_text = _get_text(soup)
    pdf_text = _get_pdf_text(email_msg)

    if pdf_text:
        text = html_text + "\n\n--- PDF ---\n" + pdf_text
    elif email_msg.body and len(email_msg.body) > len(html_text):
        text = html_text + "\n\n" + email_msg.body
    else:
        text = html_text

    pdf_segments = _parse_pdf_segments(pdf_text) if pdf_text else {}
    booking_ref = extract_booking_reference(html_text, email_msg.subject or "")
    passenger = extract_passenger(html_text)

    sections = _split_into_sections(text)

    if len(sections) > 1:
        flights = []
        for section in sections:
            flights.extend(_process_section(section, rule, booking_ref, passenger, pdf_segments))
        if flights:
            return flights
    else:
        flights = _process_section(text, rule, booking_ref, passenger, pdf_segments)
        if flights:
            return flights

    # Every path above anchors on a parenthesised IATA code. The purchase- and
    # flight-information templates carry city names only, so they land here.
    return _extract_city_itinerary(html_to_text(html), rule, booking_ref, passenger)


def _get_pdf_text(email_msg) -> str:
    """Extract text from any PDF attachments on the email message."""
    if hasattr(email_msg, "get_pdf_text"):
        return email_msg.get_pdf_text() or ""
    if hasattr(email_msg, "pdf_attachments") and email_msg.pdf_attachments:
        from ..email_connector import _extract_text_from_pdf

        parts = []
        for b in email_msg.pdf_attachments:
            t = _extract_text_from_pdf(b)
            if t:
                parts.append(t)
        return "\n".join(parts)
    return ""


# ---------------------------------------------------------------------------
# Section processing (direct + connecting flights)
# ---------------------------------------------------------------------------


def _process_section(
    section: str,
    rule,
    booking_ref: str,
    passenger: str,
    pdf_segments: dict,
) -> list[dict]:
    """Extract flights from one directional section of a LATAM itinerary."""
    segment_matches = list(_segment_re.finditer(section))
    flight_nums = re.findall(_flight_number_fragment, section)

    if len(segment_matches) < 2 or not flight_nums:
        return []

    connections = list(_connection_re.finditer(section))

    if connections:
        return _process_connecting(
            section,
            rule,
            booking_ref,
            passenger,
            pdf_segments,
            segment_matches,
            flight_nums,
            connections,
        )
    return _process_direct(rule, booking_ref, passenger, segment_matches, flight_nums)


def _process_direct(rule, booking_ref, passenger, segment_matches, flight_nums) -> list[dict]:
    """Build one flight dict per direct (non-stop) leg."""
    flights = []
    for i in range(0, len(segment_matches) - 1, 2):
        dep_m, arr_m = segment_matches[i], segment_matches[i + 1]
        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue
        fn = flight_nums[i // 2].strip() if (i // 2) < len(flight_nums) else ""
        flight = make_flight_dict(
            rule,
            fn,
            dep_m.group(3),
            arr_m.group(3),
            _build_datetime(dep_date, dep_m.group(2)),
            _build_datetime(arr_date, arr_m.group(2)),
            booking_ref,
            passenger,
        )
        if flight:
            flights.append(flight)
    return flights


def _process_connecting(
    section,
    rule,
    booking_ref,
    passenger,
    pdf_segments,
    segment_matches,
    flight_nums,
    connections,
) -> list[dict]:
    """Build individual leg dicts for a connecting itinerary."""
    dep_match = segment_matches[0]
    arr_match = segment_matches[-1]
    first_flight = flight_nums[0].strip() if flight_nums else ""

    segments = _build_segment_list(
        dep_match.group(3),
        arr_match.group(3),
        first_flight,
        connections,
    )
    n = len(segments)

    # Strategy 1: explicit dep/arr for each leg
    if len(segment_matches) >= 2 * n:
        return _flights_from_explicit_times(rule, booking_ref, passenger, segments, segment_matches)

    # Strategy 2: per-segment times from PDF
    if pdf_segments:
        flights = _flights_from_pdf(rule, booking_ref, passenger, segments, pdf_segments)
        if flights:
            return flights

    # Strategy 3: proportional split by great-circle distance
    return _flights_proportional(rule, booking_ref, passenger, segments, dep_match, arr_match)


def _build_segment_list(dep_airport, arr_airport, first_flight, connections) -> list[dict]:
    """Turn connection matches into an ordered list of leg dicts."""
    segments = []
    prev_airport = dep_airport
    for conn in connections:
        conn_airport = conn.group(1)
        conn_flight = conn.group(2).strip()
        layover_min = int(conn.group(3)) * 60 + int(conn.group(4))
        segments.append(
            {
                "dep_airport": prev_airport,
                "arr_airport": conn_airport,
                "flight_number": first_flight
                if not segments
                else segments[-1].get("next_flight", conn_flight),
                "layover_minutes": layover_min,
                "next_flight": conn_flight,
            }
        )
        prev_airport = conn_airport
    segments.append(
        {
            "dep_airport": prev_airport,
            "arr_airport": arr_airport,
            "flight_number": segments[-1]["next_flight"] if segments else first_flight,
            "layover_minutes": 0,
        }
    )
    return segments


def _flights_from_explicit_times(
    rule, booking_ref, passenger, segments, segment_matches
) -> list[dict]:
    flights = []
    for idx, seg in enumerate(segments):
        dep_m, arr_m = segment_matches[idx * 2], segment_matches[idx * 2 + 1]
        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue
        flight = make_flight_dict(
            rule,
            seg["flight_number"],
            seg["dep_airport"],
            seg["arr_airport"],
            _build_datetime(dep_date, dep_m.group(2)),
            _build_datetime(arr_date, arr_m.group(2)),
            booking_ref,
            passenger,
        )
        if flight:
            flights.append(flight)
    return flights


def _flights_from_pdf(rule, booking_ref, passenger, segments, pdf_segments) -> list[dict]:
    flights = []
    for seg in segments:
        fn = seg["flight_number"].replace(" ", "")
        if fn not in pdf_segments:
            return []  # partial match is worse than none
        dep_ds, dep_ts, arr_ds, arr_ts = pdf_segments[fn]
        dep_date = _parse_ddmmyy(dep_ds)
        arr_date = _parse_ddmmyy(arr_ds)
        if not dep_date or not arr_date:
            return []
        flight = make_flight_dict(
            rule,
            seg["flight_number"],
            seg["dep_airport"],
            seg["arr_airport"],
            _build_datetime(dep_date, dep_ts),
            _build_datetime(arr_date, arr_ts),
            booking_ref,
            passenger,
        )
        if flight:
            flights.append(flight)
    return flights if len(flights) == len(segments) else []


def _flights_proportional(
    rule, booking_ref, passenger, segments, dep_match, arr_match
) -> list[dict]:
    """Distribute total elapsed time across legs proportionally by great-circle distance."""
    dep_date = parse_flight_date(dep_match.group(1))
    arr_date = parse_flight_date(arr_match.group(1))
    if not dep_date or not arr_date:
        return []

    dep_dt = _build_datetime(dep_date, dep_match.group(2))
    arr_dt = _build_datetime(arr_date, arr_match.group(2))
    if not dep_dt or not arr_dt:
        return []

    try:
        from ...airports.timezone import localize_to_utc as _ltu

        dep_utc = _ltu(dep_dt.replace(tzinfo=None), dep_match.group(3))
        arr_utc = _ltu(arr_dt.replace(tzinfo=None), arr_match.group(3))
    except Exception:
        dep_utc, arr_utc = dep_dt, arr_dt

    total_elapsed = (arr_utc - dep_utc).total_seconds()
    total_layover = sum(s["layover_minutes"] * 60 for s in segments)
    total_flight = total_elapsed - total_layover
    if total_flight <= 0:
        return []

    distances = [_airport_distance(s["dep_airport"], s["arr_airport"]) for s in segments]
    total_dist = sum(distances) or 1
    current_dt = dep_utc

    flights = []
    for seg, dist in zip(segments, distances):
        seg_dep_dt = current_dt
        seg_arr_dt = seg_dep_dt + timedelta(seconds=total_flight * (dist / total_dist))
        flight = make_flight_dict(
            rule,
            seg["flight_number"],
            seg["dep_airport"],
            seg["arr_airport"],
            seg_dep_dt,
            seg_arr_dt,
            booking_ref,
            passenger,
        )
        if flight:
            flight["_times_already_utc"] = True
            flights.append(flight)
        current_dt = seg_arr_dt + timedelta(minutes=seg["layover_minutes"])
    return flights


# ---------------------------------------------------------------------------
# Regex fallback extractor
# ---------------------------------------------------------------------------


def extract_regex(email_msg, rule) -> list[dict]:
    """Plain-text regex fallback for LATAM emails when HTML is unavailable."""
    body = email_msg.body
    booking_ref = extract_booking_reference(email_msg.subject + "\n" + body)
    passenger = extract_passenger(body)

    sections = _split_text_sections(body)
    if len(sections) > 1:
        flights = []
        for section in sections:
            flights.extend(_process_text_section(section, rule, booking_ref, passenger))
        if flights:
            return flights
    else:
        flights = _process_text_section(body, rule, booking_ref, passenger)
        if flights:
            return flights

    return _extract_city_itinerary(body, rule, booking_ref, passenger)


def _split_text_sections(body: str) -> list[str]:
    """Split plain-text body into per-direction sections."""
    direction_starts = list(
        re.finditer(
            r"Voo de (?:ida|volta)|(?:Outbound|Return|Inbound)\s+(?:flight|journey)",
            body,
            re.IGNORECASE,
        )
    )
    if direction_starts:
        return [
            body[
                m.start() : (
                    direction_starts[i + 1].start() if i + 1 < len(direction_starts) else len(body)
                )
            ]
            for i, m in enumerate(direction_starts)
        ]

    trecho_starts = list(re.finditer(r"Trecho\s+\d+", body, re.IGNORECASE))
    if trecho_starts:
        return [
            body[
                m.start() : (
                    trecho_starts[i + 1].start() if i + 1 < len(trecho_starts) else len(body)
                )
            ]
            for i, m in enumerate(trecho_starts)
        ]

    itin_match = re.search(r"Itiner[áa]rio", body, re.IGNORECASE)
    return [body[itin_match.start() :] if itin_match else body]


def _process_text_section(section: str, rule, booking_ref: str, passenger: str) -> list[dict]:
    """Extract flights from one text section."""
    dep_match = re.search(
        _date_fragment + r"\s+" + _time_fragment + r".*?" + _airport_fragment,
        section,
        re.DOTALL,
    )
    if not dep_match:
        return []

    dep_date_str = dep_match.group(1)
    dep_time_str = dep_match.group(2)
    dep_airport = dep_match.group(3)

    all_seg_matches = list(
        re.finditer(
            _date_fragment + r"\s+" + _time_fragment + r".*?" + _airport_fragment,
            section,
            re.DOTALL,
        )
    )
    if len(all_seg_matches) < 2:
        fn_match = re.search(
            r"\("
            + re.escape(dep_airport)
            + r"\)\s+"
            + _flight_number_fragment
            + r".*?"
            + _airport_fragment,
            section,
        )
        if fn_match:
            fd = _make_segment(
                rule,
                dep_date_str,
                dep_time_str,
                dep_airport,
                dep_date_str,
                dep_time_str,
                fn_match.group(2),
                fn_match.group(1).strip(),
                booking_ref,
                passenger,
            )
            return [fd] if fd else []
        return []

    arr_match = all_seg_matches[-1]
    arr_date_str = arr_match.group(1)
    arr_time_str = arr_match.group(2)
    arr_airport = arr_match.group(3)

    first_fn_match = re.search(
        r"\(" + re.escape(dep_airport) + r"\)\s+" + _flight_number_fragment,
        section,
    )
    first_flight_num = first_fn_match.group(1).strip() if first_fn_match else ""

    connection_re = re.compile(
        r"Troca\s+de\s+avi[ãa]o\s+em:\s*([A-ZÀ-ÿ][a-zA-ZÀ-ÿ\s]*?)\s*\(([A-Z]{3})\)\s+"
        r"([A-Z0-9]{2}\s*\d{3,5}).*?Tempo\s+de\s+espera:\s*(\d+)\s*hr?\s*(\d+)\s*min",
        re.DOTALL | re.IGNORECASE,
    )
    connections = list(connection_re.finditer(section))

    if connections:
        return _text_connecting_flights(
            rule,
            dep_date_str,
            dep_time_str,
            dep_airport,
            arr_date_str,
            arr_time_str,
            arr_airport,
            first_flight_num,
            connections,
            booking_ref,
            passenger,
        )

    if first_flight_num:
        fd = _make_segment(
            rule,
            dep_date_str,
            dep_time_str,
            dep_airport,
            arr_date_str,
            arr_time_str,
            arr_airport,
            first_flight_num,
            booking_ref,
            passenger,
        )
        return [fd] if fd else []
    return []


def _make_segment(
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
    dep_date = parse_flight_date(dep_date_str)
    arr_date = parse_flight_date(arr_date_str) or dep_date
    if not dep_date:
        return None
    assert arr_date is not None
    return make_flight_dict(
        rule,
        flight_number,
        dep_airport,
        arr_airport,
        _build_datetime(dep_date, dep_time_str),
        _build_datetime(arr_date, arr_time_str),
        booking_ref,
        passenger,
    )


def _text_connecting_flights(
    rule,
    dep_date_str,
    dep_time_str,
    dep_airport,
    arr_date_str,
    arr_time_str,
    arr_airport,
    first_flight_num,
    connections,
    booking_ref,
    passenger,
) -> list[dict]:
    """Build individual legs for a connecting itinerary from plain text."""
    segments = []
    prev_airport = dep_airport
    for i, conn in enumerate(connections):
        conn_airport = conn.group(2)
        conn_flight = conn.group(3).strip()
        layover_min = int(conn.group(4)) * 60 + int(conn.group(5))
        segments.append(
            {
                "dep_airport": prev_airport,
                "arr_airport": conn_airport,
                "flight_number": first_flight_num if i == 0 else segments[-1]["next_flight"],
                "layover_after_minutes": layover_min,
                "next_flight": conn_flight,
            }
        )
        prev_airport = conn_airport
    segments.append(
        {
            "dep_airport": prev_airport,
            "arr_airport": arr_airport,
            "flight_number": segments[-1]["next_flight"] if segments else first_flight_num,
            "layover_after_minutes": 0,
            "next_flight": "",
        }
    )

    dep_date = parse_flight_date(dep_date_str)
    arr_date = parse_flight_date(arr_date_str)
    if not dep_date or not arr_date:
        return []
    try:
        dep_h, dep_m = map(int, dep_time_str.split(":"))
        arr_h, arr_m = map(int, arr_time_str.split(":"))
        dep_dt = datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m)
        arr_dt = datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m)
    except (ValueError, TypeError):
        return []

    total_elapsed = (arr_dt - dep_dt).total_seconds()
    total_layover = sum(s["layover_after_minutes"] * 60 for s in segments)
    total_flight = total_elapsed - total_layover
    if total_flight <= 0 or not segments:
        return []

    flight_per_leg = total_flight / len(segments)
    current_dt = dep_dt
    flights = []
    for seg in segments:
        seg_dep_dt = current_dt
        seg_arr_dt = seg_dep_dt + timedelta(seconds=flight_per_leg)
        fd = make_flight_dict(
            rule,
            seg["flight_number"],
            seg["dep_airport"],
            seg["arr_airport"],
            _make_aware(seg_dep_dt),
            _make_aware(seg_arr_dt),
            booking_ref,
            passenger,
        )
        if fd:
            flights.append(fd)
        current_dt = seg_arr_dt + timedelta(minutes=seg["layover_after_minutes"])
    return flights


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML+PDF (BS4), then plain-text regex."""
    if email_msg.html_body:
        result = extract_bs4(email_msg.html_body, rule, email_msg)
        if result:
            return result
    return extract_regex(email_msg, rule)


# ---------------------------------------------------------------------------
# Boarding-pass enrichment ("Aqui está o cartão de embarque para …")
# ---------------------------------------------------------------------------
# The pass mail prints, one field per line once the HTML is flattened:
#
#     Código de reserva:
#     MJGZWO
#     Voo LA8072
#     …
#     do seu voo de São Paulo a Milão que parte 16/03/26 às 06:00 PM.
#     Batman
#     da Silva
#     Assento
#     14L
#
# No arrival time anywhere, so — like every boarding pass — it enriches the leg
# the booking confirmation already created and never builds one (extract()
# finds nothing in it, which is correct). Only the 2024+ template carries a
# seat; the older "Cartão de embarque atualizado" mails print flight and date
# alone and yield nothing here either.
_bp_marker_re = re.compile(r"cart[aã]o de embarque", re.IGNORECASE)
_bp_flight_re = re.compile(r"^Voo\s+(LA[\s\xa0]?\d{3,4})\s*$", re.MULTILINE)
# Consumes the rest of its line (" PM.") so the name block starts on the next one.
_bp_departure_re = re.compile(r"que parte\s+(\d{2}/\d{2}/\d{2})\s+às\s+\d{1,2}:\d{2}[^\n]*")
_bp_seat_re = re.compile(r"^Assento\n(\d{1,3}[A-Z])\s*$", re.MULTILINE)
_bp_booking_ref_re = re.compile(r"^C[óo]digo de reserva:\n([A-Z0-9]{6})\s*$", re.MULTILINE)
_bp_name_line_re = re.compile(r"^[A-Za-zÀ-ÿ'-]+(?:\s+[A-Za-zÀ-ÿ'-]+)*$")


def extract_boarding_pass_details(email_msg) -> list[dict]:
    """Seat, booking reference and passenger from a LATAM boarding-pass mail.

    Returns enrichment records keyed on ``flight_number`` + ``departure_date``,
    the contract ``_apply_boarding_pass_details`` matches stored flights on.
    """
    from ..shared import html_to_text

    html = getattr(email_msg, "html_body", None)
    text = html_to_text(html) if html else (getattr(email_msg, "body", "") or "")
    if not _bp_marker_re.search(text):
        return []
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    fn_m = _bp_flight_re.search(text)
    dep_m = _bp_departure_re.search(text)
    if not fn_m or not dep_m:
        return []
    dep_date = _parse_ddmmyy(dep_m.group(1))
    if not dep_date:
        return []

    record = {
        "flight_number": fn_m.group(1).replace(" ", "").replace("\xa0", ""),
        "departure_date": dep_date.isoformat(),
    }
    seat_m = _bp_seat_re.search(text)
    if seat_m:
        record["seat"] = seat_m.group(1)
    ref_m = _bp_booking_ref_re.search(text)
    if ref_m:
        record["booking_reference"] = ref_m.group(1)
    # The traveller's name is the run of bare name lines between the departure
    # sentence and the "Assento" label — nothing else is printed there.
    if seat_m:
        between = text[dep_m.end() : seat_m.start()].splitlines()
        name_lines = [ln for ln in between if ln and _bp_name_line_re.match(ln)]
        if name_lines and len(name_lines) == len([ln for ln in between if ln]):
            record["passenger_name"] = " ".join(name_lines)
    return [record]
