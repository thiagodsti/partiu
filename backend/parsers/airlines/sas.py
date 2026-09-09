"""
SAS Scandinavian Airlines flight extractor.

Three extraction strategies tried in order:
  1. extract_bs4()          — HTML email parsed with BeautifulSoup.
  2. extract_regex()        — plain-text fallback (PDF tabular or block style).
  3. PDF attachment scan    — SAS e-ticket PDFs with tabular flight rows.

The regex extractor is also reused by Norwegian (similar email format).
"""

import logging
import re

from bs4 import BeautifulSoup

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _get_text,
    extract_booking_reference,
    extract_passenger,
    fix_overnight,
    get_ref_year,
    make_flight_dict,
    normalize_fn,
    parse_date,
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Flight number prefixes for SAS and its codeshare / Star Alliance partners
_FLIGHT_NUM_CODES = r"(?:SK|DY|D8|VS|LH|LX|OS|TP|A3|SN|BA|AF)"
# The code list contains real but unlucky prefixes: "A3" (Aegean) also opens
# every Airbus type SAS prints beside the real designator, so "Airbus A320neo"
# was read as Aegean flight 320 and every leg got a phantom duplicate. Requiring
# the match to stand alone as a token rules that out.
_FLIGHT_NUM_BOUNDED = rf"(?<![A-Za-z0-9])(?:{_FLIGHT_NUM_CODES}\s*\d{{2,5}})(?![A-Za-z0-9])"


def _parse_route(route_text: str) -> tuple[str, str]:
    """Parse "Stockholm Arlanda - London Heathrow" into (dep_iata, arr_iata)."""
    parts = re.split(r"\s+-\s+", route_text, maxsplit=1)
    if len(parts) != 2:
        return ("", "")
    return (resolve_iata(parts[0].strip()), resolve_iata(parts[1].strip()))


# ---------------------------------------------------------------------------
# BS4 extractor (HTML emails)
# ---------------------------------------------------------------------------


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a SAS HTML email."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)
    booking_ref = extract_booking_reference(text, email_msg.subject or "")

    date_re = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")
    route_re = re.compile(r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})")
    time_re = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    flight_num_re = re.compile(rf"({_FLIGHT_NUM_BOUNDED})")

    date_matches = list(date_re.finditer(text))
    flights = []

    for i, date_m in enumerate(date_matches):
        dep_date = parse_flight_date(date_m.group(1))
        if not dep_date:
            continue

        block_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(text)
        block = text[date_m.start() : block_end]

        fn_matches = list(flight_num_re.finditer(block))
        route_matches = list(route_re.finditer(block))
        time_matches = list(time_re.finditer(block))

        for fn_m in fn_matches:
            fn_pos = fn_m.start()
            route_m = next((r for r in reversed(route_matches) if r.start() < fn_pos), None)
            time_m = next((t for t in reversed(time_matches) if t.start() < fn_pos), None)
            if not route_m or not time_m:
                continue

            dep_dt = _build_datetime(dep_date, time_m.group(1))
            arr_dt = _build_datetime(dep_date, time_m.group(2))
            if dep_dt and arr_dt:
                arr_dt = fix_overnight(dep_dt, arr_dt)

            flight = make_flight_dict(
                rule,
                normalize_fn(fn_m.group(1)),
                route_m.group(1),
                route_m.group(2),
                dep_dt,
                arr_dt,
                booking_ref,
            )
            if flight:
                flights.append(flight)

    if not flights:
        flights = _extract_leg_card_style(text, rule, booking_ref)

    return flights


# ---------------------------------------------------------------------------
# "Leg card" BS4 extractor — newer SAS confirmation template
# ---------------------------------------------------------------------------

# Departure/arrival timestamp anchor: "23 Mar 2027 | 18:30". Unlike the
# dash-route format above, this template has no explicit "A - B" route text —
# each leg is a stack of lines (flattened to one line by _get_text):
#   23 Mar 2027 | 18:30
#   Stockholm | Arlanda ARN | Avgångsterminal 5
#   02h 50min
#   AF 1063 | Air France | Economy | 1 X Incheckat Bagage
#   23 Mar 2027 | 21:20
#   Paris | CDG | Ankomstterminal 2F
# Departure and arrival timestamps alternate strictly (dep, arr, dep, arr, ...),
# one pair per leg, so anchors are simply paired up sequentially. The IATA code
# and flight number are recovered from the text between/after each anchor
# rather than a route regex, which also picks up codeshare flight numbers
# (e.g. "AF", "KL") that aren't in SAS's own partner code list.
_LEG_CARD_ANCHOR_RE = re.compile(r"(\d{1,2}\s+[A-Za-zÀ-ÿ]{3,9}\s+\d{4})\s*\|\s*(\d{1,2}:\d{2})")
_LEG_CARD_IATA_RE = re.compile(r"\b([A-Z]{3})\b")
_LEG_CARD_FLIGHT_NUM_RE = re.compile(r"\b([A-Z]{2}\s?\d{2,5})\b(?=\s*\|)")


def _extract_leg_card_style(text: str, rule, booking_ref: str) -> list[dict]:
    """Parse the "leg card" SAS confirmation format (see module comment above)."""
    anchors = list(_LEG_CARD_ANCHOR_RE.finditer(text))
    flights = []

    for i in range(0, len(anchors) - 1, 2):
        dep_m, arr_m = anchors[i], anchors[i + 1]

        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue

        dep_window = text[dep_m.end() : arr_m.start()]
        next_anchor_start = (
            anchors[i + 2].start() if i + 2 < len(anchors) else min(len(text), arr_m.end() + 150)
        )
        arr_window = text[arr_m.end() : next_anchor_start]

        dep_iata_m = _LEG_CARD_IATA_RE.search(dep_window)
        arr_iata_m = _LEG_CARD_IATA_RE.search(arr_window)
        fn_m = _LEG_CARD_FLIGHT_NUM_RE.search(dep_window)
        if not dep_iata_m or not arr_iata_m or not fn_m:
            continue

        dep_dt = _build_datetime(dep_date, dep_m.group(2))
        arr_dt = _build_datetime(arr_date, arr_m.group(2))
        if dep_dt and arr_dt:
            arr_dt = fix_overnight(dep_dt, arr_dt)

        flight = make_flight_dict(
            rule,
            normalize_fn(fn_m.group(1)),
            dep_iata_m.group(1),
            arr_iata_m.group(1),
            dep_dt,
            arr_dt,
            booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Regex fallback extractor (plain text + PDF)
# ---------------------------------------------------------------------------


def extract_regex(email_msg, rule) -> list[dict]:
    """Plain-text regex fallback for SAS (and Norwegian) emails."""
    body = email_msg.body or ""
    booking_ref = extract_booking_reference(body, email_msg.subject or "")
    passenger = extract_passenger(body)

    flights = _extract_pdf_tabular(body, email_msg, rule, booking_ref, passenger)
    if flights:
        return flights

    return _extract_block_style(body, rule, booking_ref)


def _extract_pdf_tabular(body, email_msg, rule, booking_ref, passenger) -> list[dict]:
    """
    Parse the compact tabular format found in SAS PDF / e-ticket emails:
      SK1829 / 16MAR  Stockholm Arlanda - London Heathrow  10:00  11:50
    """
    pdf_line_re = re.compile(
        rf"(?P<flight_number>{_FLIGHT_NUM_BOUNDED})"
        r"\s*/\s*"
        r"(?P<date>\d{1,2}[A-Z]{3})"
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
    if not pdf_matches:
        return []

    ref_year = get_ref_year(email_msg)
    flights = []

    for m in pdf_matches:
        flight_number = normalize_fn(m.group("flight_number").strip())
        flight_date = parse_date(m.group("date"), ref_year)
        if not flight_date:
            continue

        # If the parsed date is before the email date, it's probably next year
        if email_msg.date and flight_date < email_msg.date.date():
            flight_date = parse_date(m.group("date"), ref_year + 1)
            if not flight_date:
                continue

        dep_airport, arr_airport = _parse_route(m.group("route").strip())
        if not dep_airport or not arr_airport:
            continue

        dep_dt = _build_datetime(flight_date, m.group("dep_time"))
        arr_dt = _build_datetime(flight_date, m.group("arr_time"))
        if dep_dt and arr_dt:
            arr_dt = fix_overnight(dep_dt, arr_dt)

        terminal = m.group("terminal") or ""
        flight = make_flight_dict(
            rule,
            flight_number,
            dep_airport,
            arr_airport,
            dep_dt,
            arr_dt,
            booking_ref,
            passenger,
        )
        if flight:
            flight["departure_terminal"] = terminal
            flights.append(flight)

    return flights


def _extract_block_style(body: str, rule, booking_ref: str) -> list[dict]:
    """
    Parse the "Din resa" / HTML-to-text block format:
      16 March 2026
      ARN – London Heathrow LHR
      SK1829  10:00 – 11:50
    """
    date_re = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")
    route_re = re.compile(r"([A-Z]{3})\s*[-–]\s*(?:[A-ZÀ-ÿ][A-Za-zÀ-ÿ\s-]*?\s+)?([A-Z]{3})")
    time_re = re.compile(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})")
    flight_num_re = re.compile(rf"({_FLIGHT_NUM_BOUNDED})")

    date_matches = list(date_re.finditer(body))
    flights = []

    for i, date_m in enumerate(date_matches):
        dep_date = parse_flight_date(date_m.group(1))
        if not dep_date:
            continue

        block_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(body)
        block = body[date_m.start() : block_end]

        routes = list(route_re.finditer(block))
        times = list(time_re.finditer(block))
        fns = list(flight_num_re.finditer(block))

        for j in range(min(len(routes), len(times), len(fns))):
            dep_dt = _build_datetime(dep_date, times[j].group(1))
            arr_dt = _build_datetime(dep_date, times[j].group(2))
            if dep_dt and arr_dt:
                arr_dt = fix_overnight(dep_dt, arr_dt)

            flight = make_flight_dict(
                rule,
                normalize_fn(fns[j].group(1)),
                routes[j].group(1),
                routes[j].group(2),
                dep_dt,
                arr_dt,
                booking_ref,
            )
            if flight:
                flights.append(flight)

    return flights


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: HTML (BS4) → plain-text regex → PDF attachments."""
    if email_msg.html_body:
        flights = extract_bs4(email_msg.html_body, rule, email_msg)
        if flights:
            return flights

    flights = extract_regex(email_msg, rule)
    if flights:
        return flights

    # Some SAS e-ticket emails carry flight data only in a PDF attachment
    if email_msg.pdf_attachments:
        from ..email_connector import _extract_text_from_pdf

        booking_ref = extract_booking_reference("", email_msg.subject or "")
        passenger = extract_passenger("")

        for pdf_bytes in email_msg.pdf_attachments:
            pdf_text = _extract_text_from_pdf(pdf_bytes)
            if not pdf_text:
                continue
            booking_ref = extract_booking_reference(pdf_text, email_msg.subject or "")
            passenger = extract_passenger(pdf_text)
            flights = _extract_pdf_tabular(pdf_text, email_msg, rule, booking_ref, passenger)
            if flights:
                return flights

    return []
