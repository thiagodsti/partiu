"""
Turkish Airlines (TK) ticket-details / booking-confirmation parser.

Turkish Airlines sends its own branded "Ticket Details" mail through its ESP,
not a GDS ticket receipt — ``gds_eticket`` finds no receipt marker in it — so the
itinerary only exists in these two renderings of the same document.

HTML body, as ``html_to_text`` renders it, one block per leg::

    Istanbul (IST) - Denizli (DNZ)     ← route header
    21 September 2026 Monday           ← travel date
    Economy Class (P) - EcoFly
    06:35
    IST
    Direct flight                      ← or the connection labels, on 1-3 lines
    TK2576
    07:40
    DNZ

PDF attachment (``TicketDetails.pdf``), the same legs as a detail block::

    Istanbul (IST) - Denizli (DNZ) 21 September 2026 Monday
    ...
    06:35 ISTANBUL (TÜRKİYE) Istanbul Airport (IST)
    Airline - Flight no: TURKISH AIRLINES - TK2576
    Aircraft type: Narrow-body - Airbus A319-100
    07:40 DENİZLİ (TÜRKİYE) Denizli Cardak Airport (DNZ)

Neither rendering repeats the date inside the leg block, so both paths resolve it
from the nearest *header* line above the block — a line that is either a bare
date or a route header. Taking "the nearest line that parses as a date" instead
would reach the ``Transaction date:`` line at the top of the mail and date every
leg to the day the ticket was issued.
"""

import logging
import re

from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    get_email_text,
    make_flight_dict,
    normalize_fn,
)

logger = logging.getLogger(__name__)

# A date inside a header line: "21 September 2026", "21 Eylül 2026".
_DATE_RE = re.compile(r"\b(\d{1,2}\s+[^\W\d_]{3,12}\.?\s+\d{4})\b")
# A line that is nothing but that date, optionally followed by the weekday name.
_DATE_ONLY_LINE_RE = re.compile(r"^\d{1,2}\s+[^\W\d_]{3,12}\.?\s+\d{4}(?:\s+[^\W\d_]+)?$")
# "Istanbul (IST) - Denizli (DNZ)" — the route header, in both renderings.
_ROUTE_HEADER_RE = re.compile(r"\([A-Z]{3}\)[^(\n]*-[^(\n]*\([A-Z]{3}\)")
# "Economy Class (P)" / "Premium Economy Class (W)" / "Ekonomi Sınıfı (P)".
# Every word in the cabin name must carry a lowercase tail, so the PDF's
# "IST DNZ Economy Class (P)" yields "Economy" rather than the IATA codes.
_CABIN_WORD = r"\w[a-zà-öø-ÿçğıöşü]+"
_CABIN_RE = re.compile(
    rf"((?:{_CABIN_WORD}[ \t]+){{0,2}}{_CABIN_WORD})[ \t]+(?:Class|S[ıi]n[ıi]f[ıi])\s*\("
)

# One leg in the HTML rendering.
_HTML_LEG_RE = re.compile(
    r"^(?P<dep_time>\d{1,2}:\d{2})\n"
    r"(?P<dep_iata>[A-Z]{3})\n"
    r"(?:[^\n]{0,80}\n){0,3}?"  # "Direct flight", stop/connection labels
    r"(?P<fn>[A-Z]{2}[ \xa0]?\d{2,4})\n"
    r"(?P<arr_time>\d{1,2}:\d{2})\n"
    r"(?P<arr_iata>[A-Z]{3})$",
    re.MULTILINE,
)

# "06:35 ISTANBUL (TÜRKİYE) Istanbul Airport (IST)" — one endpoint of a PDF leg.
_PDF_STOP_RE = re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+\S.*\((?P<iata>[A-Z]{3})\)\s*$")
_PDF_FLIGHT_NO_RE = re.compile(r"\b([A-Z]{2}[ \xa0]?\d{2,4})\b")

# How far above a leg block its header may sit. Generous on purpose: a connection
# prints both legs under a single header, so the second block's date can be a
# dozen lines up. Distance is not what keeps the "Transaction date:" line out —
# the line-shape requirement in _header_date is.
_LOOKBACK = 24

# "Mr. EDIZ TEKOK" — the greeting names the ticket holder. Read here rather than
# left to the shared passenger extractor: this layout also prints a "Passenger
# name" heading whose next line is a route ("Istanbul - Denizli"), which the
# shared label pattern picks up as the passenger.
_GREETING_RE = re.compile(
    r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof|Say[ıi]n|Bay|Bayan)\.?\s+"
    r"([^\W\d_][^\W\d_]*(?:[ \t]+[^\W\d_][^\W\d_]*)+)\s*,?$",
    re.MULTILINE,
)

# "Reservation code: T2TQXB", and the PDF's three-line version where the
# greeting lands between the label and the code:
#   Your ticket has been created. Reservation code
#   Mr. EDIZ TEKOK
#   T2TQXB
# The shared booking-reference extractor stops at the first non-separator
# character after the label, so it reaches neither rendering.
_BOOKING_REF_RE = re.compile(
    r"(?:Reservation\s+code|Rezervasyon\s+kodu)[^\n]*?"
    r"(?:\n[^\n]*){0,2}?[:\s\n]+(?-i:([A-Z0-9]{6}))\b",
    re.IGNORECASE,
)


def _header_date(lines: list[str], idx: int):
    """Date from the nearest bare-date or route-header line above line *idx*."""
    for line in reversed(lines[max(0, idx - _LOOKBACK) : idx]):
        if not (_ROUTE_HEADER_RE.search(line) or _DATE_ONLY_LINE_RE.match(line)):
            continue
        m = _DATE_RE.search(line)
        if m and (parsed := parse_flight_date(m.group(1))):
            return parsed
    return None


def _header_cabin(lines: list[str], idx: int) -> str:
    """Cabin name from the header lines above line *idx* ("Economy Class (P)")."""
    for line in reversed(lines[max(0, idx - _LOOKBACK) : idx]):
        m = _CABIN_RE.search(line)
        if m:
            return m.group(1).strip()
    return ""


def _build_leg(
    rule,
    lines: list[str],
    line_idx: int,
    fn: str,
    dep_iata: str,
    arr_iata: str,
    dep_time: str,
    arr_time: str,
) -> dict | None:
    """Assemble one leg, taking its date and cabin from the header above it."""
    dep_date = _header_date(lines, line_idx)
    if not dep_date:
        logger.debug("Turkish Airlines: no header date above leg %s at line %d", fn, line_idx)
        return None

    dep_dt = _build_datetime(dep_date, dep_time)
    arr_dt = _build_datetime(dep_date, arr_time)
    if dep_dt and arr_dt:
        arr_dt = fix_overnight(dep_dt, arr_dt)

    flight = make_flight_dict(rule, normalize_fn(fn), dep_iata, arr_iata, dep_dt, arr_dt)
    if flight:
        flight["cabin_class"] = _header_cabin(lines, line_idx)
    return flight


def _legs_from_html(text: str, rule) -> list[dict]:
    """Parse the legs out of the HTML rendering."""
    lines = text.split("\n")
    flights = []
    for m in _HTML_LEG_RE.finditer(text):
        flight = _build_leg(
            rule,
            lines,
            text.count("\n", 0, m.start()),
            m.group("fn"),
            m.group("dep_iata"),
            m.group("arr_iata"),
            m.group("dep_time"),
            m.group("arr_time"),
        )
        if flight:
            flights.append(flight)
    return flights


def _legs_from_pdf_text(text: str, rule) -> list[dict]:
    """Parse the legs out of the PDF rendering's per-leg detail blocks.

    Endpoint lines are paired only when a flight number appears between them, so
    the gap between one leg's arrival and the next leg's departure — which holds
    no flight number — never becomes a leg of its own.
    """
    lines = text.split("\n")
    stops = [(i, m) for i, line in enumerate(lines) if (m := _PDF_STOP_RE.match(line))]

    flights = []
    i = 0
    while i + 1 < len(stops):
        (dep_idx, dep), (arr_idx, arr) = stops[i], stops[i + 1]
        fn = ""
        for line in lines[dep_idx + 1 : arr_idx]:
            if fn_match := _PDF_FLIGHT_NO_RE.search(line):
                fn = fn_match.group(1)
                break
        if not fn:
            i += 1
            continue
        flight = _build_leg(
            rule,
            lines,
            dep_idx,
            fn,
            dep.group("iata"),
            arr.group("iata"),
            dep.group("time"),
            arr.group("time"),
        )
        if flight:
            flights.append(flight)
        i += 2
    return flights


def _apply_metadata(flights: list[dict], text: str) -> None:
    """Set the passenger and booking reference from TK's own labels.

    Both are taken here rather than left to the shared extractors, which this
    layout defeats: the "Passenger name" heading is followed by a route
    ("Istanbul - Denizli"), and in the PDF rendering the greeting sits between
    the "Reservation code" label and the code itself.
    """
    greeting = _GREETING_RE.search(text)
    booking_ref = _BOOKING_REF_RE.search(text)
    for flight in flights:
        if greeting:
            flight["passenger_name"] = greeting.group(1).strip()
        if booking_ref:
            flight["booking_reference"] = booking_ref.group(1)


def extract(email_msg, rule) -> list[dict]:
    """Extract flights from a Turkish Airlines ticket-details email."""
    text = get_email_text(email_msg)
    flights = _legs_from_html(text, rule)

    if not flights and email_msg.pdf_attachments:
        pdf_text = email_msg.get_pdf_text()
        if pdf_text:
            flights = _legs_from_pdf_text(pdf_text, rule)
            if flights:
                text = f"{text}\n{pdf_text}"

    _apply_metadata(flights, text)
    return enrich_flights(flights, text, email_msg.subject)
