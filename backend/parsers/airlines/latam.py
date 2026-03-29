"""
LATAM Airlines flight extractor.

Two extraction strategies:
  1. extract_bs4()   — HTML email body parsed with BeautifulSoup.
                       Also reads PDF attachments for per-segment times.
  2. extract_regex() — plain-text fallback when HTML is unavailable.
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
    _extract_booking_reference,
    _extract_passenger_name,
    _get_text,
    _make_aware,
    _make_flight_dict,
)

logger = logging.getLogger(__name__)

# Regex building blocks reused in both the BS4 and regex extractors
_DATE_RE = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
_TIME_RE = r"(\d{1,2}:\d{2})"
_AIRPORT_RE = r"\(([A-Z]{3})\)"
_FLIGHT_NUM_RE = r"([A-Z0-9]{2}\s*\d{3,5})(?!\w)"

_SEGMENT_RE = re.compile(
    _DATE_RE + r"\s+" + _TIME_RE + r".*?" + _AIRPORT_RE,
    re.DOTALL,
)
_CONNECTION_RE = re.compile(
    r"Troca\s+de\s+avi[ãa]o\s+em:.*?\(([A-Z]{3})\)\s+"
    r"([A-Z0-9]{2}\s*\d{3,5}).*?"
    r"Tempo\s+de\s+espera:\s*(\d+)\s*hr?\s*(\d+)\s*min",
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
    """
    Parse the LATAM PDF itinerary table (format: DD/MM/YY HH:MM).

    Returns a dict mapping normalised flight number (no spaces) to
    (dep_date_str, dep_time_str, arr_date_str, arr_time_str).

    Example PDF row:
      LA8072 (Guarulhos) (Malpensa) 16/03/26 18:00 17/03/26 09:15 Economy Light
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
    if result:
        logger.debug("LATAM PDF segments parsed: %s", list(result.keys()))
    return result


# ---------------------------------------------------------------------------
# BS4 extractor
# ---------------------------------------------------------------------------


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """
    Extract flights from a LATAM HTML email.

    Splits the text into directional sections (outbound / return) and processes
    each one. Falls back to PDF attachment times when the HTML lacks per-segment
    departure/arrival info for connecting flights.
    """
    soup = BeautifulSoup(html, "lxml")
    html_text = _get_text(soup)

    # LATAM often attaches a full itinerary PDF with per-segment times
    pdf_text = _get_pdf_text(email_msg)

    # Build the full text blob that will be split into sections
    if pdf_text:
        text = html_text + "\n\n--- PDF ---\n" + pdf_text
    elif email_msg.body and len(email_msg.body) > len(html_text):
        text = html_text + "\n\n" + email_msg.body
    else:
        text = html_text

    pdf_segments = _parse_pdf_segments(pdf_text) if pdf_text else {}
    booking_ref = _extract_booking_reference(soup, email_msg.subject)
    passenger = _extract_passenger_name(soup)

    sections = _split_into_sections(text)

    flights = []
    for section in sections:
        flights.extend(_process_section(section, rule, booking_ref, passenger, pdf_segments))
    return flights


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


def _split_into_sections(text: str) -> list[str]:
    """Split itinerary text into one section per flight direction."""
    # "Voo de ida / volta" or "Outbound / Return flight"
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

    # "Trecho 1 / Trecho 2 / …" style
    trecho_splits = re.split(r"Trecho\s+\d+", text, flags=re.IGNORECASE)
    if len(trecho_splits) > 1:
        return trecho_splits[1:]

    return [text]


def _process_section(
    section: str, rule, booking_ref: str, passenger: str, pdf_segments: dict
) -> list[dict]:
    """Extract flights from one directional section of a LATAM itinerary."""
    segment_matches = list(_SEGMENT_RE.finditer(section))
    flight_nums = re.findall(_FLIGHT_NUM_RE, section)

    if len(segment_matches) < 2 or not flight_nums:
        return []

    connections = list(_CONNECTION_RE.finditer(section))

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
    else:
        return _process_direct(rule, booking_ref, passenger, segment_matches, flight_nums)


def _process_direct(rule, booking_ref, passenger, segment_matches, flight_nums) -> list[dict]:
    """Build one flight dict per direct (non-stop) leg."""
    flights = []
    for i in range(0, len(segment_matches) - 1, 2):
        dep_m = segment_matches[i]
        arr_m = segment_matches[i + 1]
        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue
        fn = flight_nums[i // 2].strip() if (i // 2) < len(flight_nums) else ""
        flight = _make_flight_dict(
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
        dep_match.group(3), arr_match.group(3), first_flight, connections
    )
    n = len(segments)

    # Strategy 1: email has explicit dep/arr for each individual leg
    if len(segment_matches) >= 2 * n:
        return _flights_from_explicit_times(rule, booking_ref, passenger, segments, segment_matches)

    # Strategy 2: per-segment times from the PDF attachment
    if pdf_segments:
        flights = _flights_from_pdf(rule, booking_ref, passenger, segments, pdf_segments)
        if flights:
            return flights

    # Strategy 3: proportional split by great-circle distance
    return _flights_proportional(rule, booking_ref, passenger, segments, dep_match, arr_match)


def _build_segment_list(dep_airport, arr_airport, first_flight, connections) -> list[dict]:
    """Turn a list of connection matches into an ordered list of leg dicts."""
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
        dep_m = segment_matches[idx * 2]
        arr_m = segment_matches[idx * 2 + 1]
        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue
        flight = _make_flight_dict(
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
        flight = _make_flight_dict(
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
    if len(flights) == len(segments):
        logger.debug("Used PDF segment times for %d LATAM flights", len(flights))
        return flights
    return []


def _flights_proportional(
    rule, booking_ref, passenger, segments, dep_match, arr_match
) -> list[dict]:
    """
    Distribute total elapsed time across legs proportionally by great-circle distance.
    Used when neither explicit per-leg times nor PDF data are available.
    """
    dep_date = parse_flight_date(dep_match.group(1))
    arr_date = parse_flight_date(arr_match.group(1))
    if not dep_date or not arr_date:
        return []

    dep_dt = _build_datetime(dep_date, dep_match.group(2))
    arr_dt = _build_datetime(arr_date, arr_match.group(2))
    if not dep_dt or not arr_dt:
        return []

    try:
        from ...timezone_utils import localize_to_utc as _ltu

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
        flight = _make_flight_dict(
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
    """
    Plain-text regex fallback for LATAM emails when HTML is unavailable.
    Mirrors the BS4 extractor logic but operates on email_msg.body.
    """
    body = email_msg.body
    booking_ref = _booking_ref_from_text(email_msg.subject + "\n" + body)
    passenger = _passenger_from_text(body)

    sections = _split_text_sections(body)
    flights = []
    for section in sections:
        flights.extend(_process_text_section(section, rule, booking_ref, passenger))
    return flights


def _booking_ref_from_text(text: str) -> str:
    m = re.search(
        r"(?:C[óo]digo\s+de\s+reserva|booking\s*(?:ref|code|reference)|"
        r"Bokning|Reserva|PNR|confirmation\s*code)[:\s\[]+([A-Z0-9]{5,8})",
        text,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _passenger_from_text(text: str) -> str:
    m = re.search(
        r"(?:Lista\s+de\s+passageiros|passenger\s*(?:list|name))"
        r"[\s:]*[-•·]?\s*([A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zA-ZÀ-ÿ]+)*)",
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


def _split_text_sections(body: str) -> list[str]:
    """Split plain-text body into per-direction sections (same logic as BS4)."""
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
    dep_match = re.search(_DATE_RE + r"\s+" + _TIME_RE + r".*?" + _AIRPORT_RE, section, re.DOTALL)
    if not dep_match:
        return []

    dep_date_str = dep_match.group(1)
    dep_time_str = dep_match.group(2)
    dep_airport = dep_match.group(3)

    all_seg_matches = list(
        re.finditer(_DATE_RE + r"\s+" + _TIME_RE + r".*?" + _AIRPORT_RE, section, re.DOTALL)
    )
    if len(all_seg_matches) < 2:
        # Only one date/time/airport found — try simpler pattern
        fn_match = re.search(
            r"\(" + re.escape(dep_airport) + r"\)\s+" + _FLIGHT_NUM_RE + r".*?" + _AIRPORT_RE,
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

    first_fn_match = re.search(r"\(" + re.escape(dep_airport) + r"\)\s+" + _FLIGHT_NUM_RE, section)
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
    assert arr_date is not None  # arr_date falls back to dep_date which is non-None here
    try:
        dep_h, dep_m = map(int, dep_time_str.split(":"))
        arr_h, arr_m = map(int, arr_time_str.split(":"))
        dep_dt = _make_aware(datetime(dep_date.year, dep_date.month, dep_date.day, dep_h, dep_m))
        arr_dt = _make_aware(datetime(arr_date.year, arr_date.month, arr_date.day, arr_h, arr_m))
    except (ValueError, TypeError):
        return None
    return _make_flight_dict(
        rule, flight_number, dep_airport, arr_airport, dep_dt, arr_dt, booking_ref, passenger
    )


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML+PDF (BS4), then plain-text regex."""
    if email_msg.html_body:
        result = extract_bs4(email_msg.html_body, rule, email_msg)
        if result:
            return result
    return extract_regex(email_msg, rule)


# ---------------------------------------------------------------------------
# Boarding-pass seat updater (check-in confirmation emails)
# ---------------------------------------------------------------------------

_BP_KEYWORD_RE = re.compile(
    r"cart[ãa]o\s+de\s+embarque|check.?in\s+feito|boarding\s+pass",
    re.IGNORECASE,
)
_BP_FN_RE = re.compile(r"\b(LA\s*\d{3,5})\b")
_BP_DATE_RE = re.compile(r"\b(\d{1,2}/\d{2}/\d{2})\b")
# Seat comes right after "Check-in feito" section header, on its own short line
_BP_SEAT_SECTION_RE = re.compile(
    r"Check-in\s+feito[^<\n]*\n[\s\S]{0,200}?\n\s*(\d{1,3}[A-Z])\s*\n",
    re.IGNORECASE,
)


def extract_seat_update(email_msg) -> dict | None:
    """
    Try to extract a seat assignment from a LATAM boarding-pass email.

    Returns {"flight_number": str, "dep_date": str, "seat": str}
    if this looks like a check-in confirmation with a seat, else None.
    """
    body = email_msg.body or ""
    if not _BP_KEYWORD_RE.search(body):
        return None

    fn_m = _BP_FN_RE.search(body)
    if not fn_m:
        return None

    date_m = _BP_DATE_RE.search(body)
    if not date_m:
        return None
    dep_date = _parse_ddmmyy(date_m.group(1))
    if not dep_date:
        return None

    seat_m = _BP_SEAT_SECTION_RE.search(body)
    if not seat_m:
        return None

    return {
        "flight_number": fn_m.group(1).replace(" ", ""),
        "dep_date": dep_date.isoformat(),
        "seat": seat_m.group(1),
    }


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
    """Build individual legs for a connecting itinerary extracted from plain text."""
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
        fd = _make_flight_dict(
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
