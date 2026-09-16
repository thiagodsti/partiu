"""
Lufthansa flight extractor (BS4 only — no plain-text regex fallback needed).

Handles four confirmed email formats:
  1. Itinerary table — "Your itinerary" / "O seu itinerário" (booking.lufthansa.com,
     booking-lufthansa.com, and the 15below template). One block per leg:
       "Fri. 29 March 2024:" / "seg. 20. dezembro 2021:"
       "06:45 h" / "16:20 Hora"   → "Stockholm Arlanda (ARN)" → "Terminal 5"
       "09:00 h"  [ "+1" ]        → "Frankfurt Frankfurt (FRA)" → "Terminal 1"
       "LH 809" → "operated by: Lufthansa" → "Status: confirmed"
     Parsed by ``_extract_itinerary`` as a line-driven block scan rather than one
     regex, because every one of those lines is optional in some variant.
  2. Standard e-ticket / itinerary (lufthansa.com):
       "16 Mar 2026  10:00  (FRA) ... LH1234 ... 11:50  (LHR)"
  3. Mobile boarding pass / check-in confirmed (lufthansa.com):
       "LH803\\nFlight\\n24JAN19\\nDate\\nARN\\n...\\nFRA\\n...\\n14:00\\nPartida\\nVT353Y\\nCódigo da reserva"
  4. Check-in available notification (your.lufthansa-group.com):
       "ARN\\n–\\nFRA\\n...\\nLH803\\n24.01.2019\\nData\\n...\\n14:00\\nPartida\\n16:05\\nChegada"
"""

import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from ..cancellations import booking_cancellation
from ..engine import parse_flight_date
from ..shared import (
    _build_datetime,
    _get_text,
    extract_booking_reference,
    extract_passenger,
    fix_overnight,
    get_email_text,
    html_to_text,
    is_valid_iata,
    make_flight_dict,
    normalize_fn,
)

# ---------------------------------------------------------------------------
# Format 1: standard e-ticket  (date + time + (IATA) triplets)
# ---------------------------------------------------------------------------
_date_fragment = r"(\d{1,2}\s+(?:de\s+)?[A-Za-zÀ-ÿ]+\.?\s+(?:de\s+)?\d{4})"
_time_fragment = r"(\d{1,2}:\d{2})"
_airport_fragment = r"\(([A-Z]{3})\)"
_date_time_airport_re = re.compile(
    _date_fragment + r"\s+" + _time_fragment + r".*?" + _airport_fragment,
    re.DOTALL,
)
_flight_number_re = re.compile(r"(LH[\s\xa0]*\d{3,5})")

# ---------------------------------------------------------------------------
# Format 1 (itinerary table): per-line patterns for the block scan
# ---------------------------------------------------------------------------
# A leg opens with a date header. The weekday abbreviation is localised
# ("Fri.", "Thur.", "seg.", "qui.", "Do."), so it is stripped generically rather
# than enumerated; what identifies the line is that the remainder parses as a
# date. A trailing ":" and the German/Portuguese dot after the day ("20.
# dezembro 2021") are normalised away first.
_itin_weekday_prefix_re = re.compile(r"^[A-Za-zÀ-ÿ]{2,10}\.?,?\s+")
_itin_day_dot_re = re.compile(r"^(\d{1,2})\.\s*")
# "06:45 h" / "16:20 Hora" / "14:00 Uhr" — the unit suffix is what separates an
# itinerary time from the many other HH:MM values on the page (durations, deadlines).
_itin_time_re = re.compile(r"^(\d{1,2}):(\d{2})[\s\xa0]*(?:h|hora|hrs?|uhr)\.?$", re.IGNORECASE)
# "Stockholm Arlanda (ARN)" — the IATA code closes the airport line.
_itin_airport_re = re.compile(r"\(([A-Z]{3})\)\s*$")
_itin_terminal_re = re.compile(r"^Terminal[\s\xa0]+(\S+)$", re.IGNORECASE)
# "+1" on its own line: the arrival lands the next day. Lufthansa states this
# explicitly, so we never have to infer an overnight from the clock alone.
_itin_next_day_re = re.compile(r"^\+(\d)$")
# "LH803" / "LH 809" / "LX 4709" — any marketing carrier, not just LH. A
# Lufthansa booking routinely sells LX/OS/SN legs, and pinning this to "LH"
# silently dropped every one of them.
_itin_flight_re = re.compile(r"^([A-Z]{2}[\s\xa0]?\d{1,4})$")
# "Cancelada" / "cancelled" / "storniert" — a schedule-change mail lists the
# dropped leg alongside the new ones; storing it would invent a flight the
# passenger never takes.
_itin_cancelled_re = re.compile(r"cancel|stornier|anulad", re.IGNORECASE)
_itin_status_label_re = re.compile(r"^(?:Status|Estatuto|Estado|Statut)\s*:?$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Format 3: mobile boarding pass / check-in confirmed
# ---------------------------------------------------------------------------
_boarding_pass_flight_date_re = re.compile(
    r"(LH[\s\xa0]*\d{3,5})\n"
    r"(?:Flight|Voo)\n"
    r"(\d{2}[A-Z]{3}\d{2,4})\n"  # date "24JAN19"
    r"(?:Date|Data)\n"
    r"([A-Z]{3})\n"  # dep IATA
    r"[^\n]+\n"  # city name
    r"([A-Z]{3})\n"  # arr IATA
)
_boarding_pass_departure_time_re = re.compile(r"(\d{2}:\d{2})\n(?:Partida|Departure|Abflug)\b")
_boarding_pass_booking_ref_re = re.compile(
    r"([A-Z0-9]{5,8})\n(?:C[óo]digo\s+da\s+reserva|Booking\s+(?:code|reference)|Buchungscode)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Format 4: check-in available notification
# ---------------------------------------------------------------------------
_checkin_leg_re = re.compile(
    r"[A-Za-z][A-Za-z /.-]+\n"  # dep city name
    r"([A-Z]{3})\n"  # g1: dep IATA
    r"[–\-]\n"  # separator
    r"[A-Za-z][A-Za-z /.-]+\n"  # arr city name
    r"([A-Z]{3})\n"  # g2: arr IATA
    r"(?:[^\n]+\n){0,8}"
    r"(LH[\s\xa0]*\d{3,5})\n"  # g3: flight number
    r"(\d{2}\.\d{2}\.\d{4})\n"  # g4: date "24.01.2019"
    r"(?:Data|Date|Datum)\n"
    r"(?:[^\n]+\n){0,3}"
    r"(\d{2}:\d{2})\n"  # g5: dep time
    r"(?:Partida|Departure|Abflug)\n"
    r"(\d{2}:\d{2})\n"  # g6: arr time
    r"(?:Chegada|Arrival|Ankunft)\n",
)
_date_ddmmyyyy_re = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def _parse_ddmmyyyy(s: str) -> date | None:
    m = _date_ddmmyyyy_re.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Format extractors (each returns list[dict])
# ---------------------------------------------------------------------------


def _extract_f1(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 1: standard e-ticket with date+time+(IATA) triplets."""
    dta_matches = list(_date_time_airport_re.finditer(text))
    fn_matches = list(_flight_number_re.finditer(text))

    flights = []
    for i in range(0, len(dta_matches) - 1, 2):
        dep_m, arr_m = dta_matches[i], dta_matches[i + 1]
        dep_date = parse_flight_date(dep_m.group(1))
        arr_date = parse_flight_date(arr_m.group(1))
        if not dep_date or not arr_date:
            continue

        fn = ""
        for fn_m in fn_matches:
            if dep_m.start() <= fn_m.start() <= arr_m.start():
                fn = normalize_fn(fn_m.group(1))
                break

        flight = make_flight_dict(
            rule,
            fn,
            dep_m.group(3),
            arr_m.group(3),
            _build_datetime(dep_date, dep_m.group(2)),
            _build_datetime(arr_date, arr_m.group(2)),
            booking_ref,
        )
        if flight:
            flights.append(flight)

    return flights


def _itin_date_header(line: str) -> date | None:
    """Parse an itinerary leg's date header, or return None if it isn't one.

    Handles "Fri. 29 March 2024:", "Thur. 24 January 2019" and the Portuguese
    "seg. 20. dezembro 2021:" — the weekday is localised and the day may carry a
    trailing dot, so both are normalised before parsing.
    """
    s = line.strip().rstrip(":").strip()
    if not s or len(s) > 60:
        return None
    d = parse_flight_date(s)
    if d:
        return d
    s = _itin_weekday_prefix_re.sub("", s, count=1)
    s = _itin_day_dot_re.sub(r"\1 ", s, count=1)
    return parse_flight_date(s)


def _itin_leg_bounds(lines: list[str]) -> list[tuple[int, date]]:
    """Return (line index, date) for every itinerary leg header in *lines*."""
    return [(i, d) for i, ln in enumerate(lines) if (d := _itin_date_header(ln)) is not None]


def _itin_parse_leg(lines: list[str], dep_date: date, rule, booking_ref: str) -> dict | None:
    """Build one flight from the lines of a single itinerary leg block.

    The block is a fixed sequence — dep time, dep airport, [terminal], arr time,
    [+N], arr airport, [terminal], flight number, operator, status — but any of
    the optional entries may be absent, so each line is classified on its own and
    the pieces are assembled by order of appearance.
    """
    times: list[str] = []
    airports: list[str] = []
    terminals: dict[int, str] = {}  # airport index → terminal
    fn = ""
    day_offset = 0
    saw_arrival_time = False
    cancelled = False
    expect_status = False

    for ln in lines:
        line = ln.strip()

        if expect_status:
            expect_status = False
            if _itin_cancelled_re.search(line):
                cancelled = True
                continue
        if _itin_status_label_re.match(line):
            expect_status = True
            continue

        m = _itin_time_re.match(line)
        if m:
            times.append(f"{m.group(1)}:{m.group(2)}")
            saw_arrival_time = len(times) >= 2
            continue

        m = _itin_next_day_re.match(line)
        if m and saw_arrival_time:
            day_offset = int(m.group(1))
            continue

        m = _itin_terminal_re.match(line)
        if m:
            if airports:
                terminals[len(airports) - 1] = m.group(1)
            continue

        m = _itin_airport_re.search(line)
        if m and is_valid_iata(m.group(1)):
            airports.append(m.group(1))
            continue

        if not fn:
            m = _itin_flight_re.match(line)
            if m:
                fn = normalize_fn(m.group(1))

    if cancelled or not fn or len(times) < 2 or len(airports) < 2:
        return None

    dep_dt = _build_datetime(dep_date, times[0])
    arr_dt = _build_datetime(dep_date + timedelta(days=day_offset), times[1])
    if not dep_dt or not arr_dt:
        return None
    # The explicit "+N" marker already moved the arrival date; only guess at an
    # overnight when the email gave us no marker to go on.
    if not day_offset:
        arr_dt = fix_overnight(dep_dt, arr_dt)

    flight = make_flight_dict(rule, fn, airports[0], airports[1], dep_dt, arr_dt, booking_ref)
    if flight:
        flight["departure_terminal"] = terminals.get(0, "")
        flight["arrival_terminal"] = terminals.get(1, "")
    return flight


def _extract_itinerary(text_nl: str, rule, booking_ref: str) -> list[dict]:
    """Format 1: the "Your itinerary" / "O seu itinerário" leg table."""
    lines = [ln for ln in text_nl.split("\n") if ln.strip()]
    headers = _itin_leg_bounds(lines)
    if not headers:
        return []

    flights = []
    for idx, (start, dep_date) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        flight = _itin_parse_leg(lines[start + 1 : end], dep_date, rule, booking_ref)
        if flight:
            flights.append(flight)
    return flights


def _extract_f3(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 3: Lufthansa mobile boarding pass — yields **no flights**, by design.

    This layout prints the flight number, route, date and *departure* time, and
    no arrival time at all. It used to stand the departure in for the arrival,
    which produced a zero-length leg that `validation.py` then discarded on
    every sync — the flight was never stored, and the only trace was a log line
    reading like a parse failure rather than a format missing a field.

    A boarding pass is not how a flight is learned; it is how a flight already
    known is enriched. That is the rule `_process_bcbp_email` has always
    followed ("we don't have enough info to create a complete flight from BCBP
    alone"), and a mobile boarding pass carries strictly less than a BCBP
    barcode does. The seat, gate, terminal and cabin it *does* carry are read by
    `extract_boarding_pass_details` below and patched onto the stored flight.

    Measured against the 372-email corpus: all three emails in this format were
    for legs already stored from their booking confirmations, with real arrival
    times. Nothing is lost by refusing to invent one.
    """
    return []


# Value-then-label is how this layout prints every field ("19B\nSeat",
# "A20\nGate"), which is why these read backwards compared with the itinerary
# formats above.
_bp_seat_re = re.compile(r"([0-9]{1,3}[A-Z])\n(?:Seat|Assento|Sitzplatz|Platz)\b", re.IGNORECASE)
_bp_gate_re = re.compile(r"([A-Z]?[0-9]{1,3}[A-Z]?)\n(?:Gate|Porta|Flugsteig)\b", re.IGNORECASE)
_bp_terminal_re = re.compile(r"(?:Terminal)\s*:?\s*(\S+)", re.IGNORECASE)
_bp_cabin_re = re.compile(r"([A-Z][A-Z ]{2,20})\n(?:Class|Classe|Klasse)\b")
_bp_passenger_re = re.compile(
    r"^(.+)\n(?:Passenger name|Nome do passageiro|Passagiername)\b", re.MULTILINE
)


def extract_boarding_pass_details(email_msg) -> list[dict]:
    """Seat/gate/terminal/cabin from a Lufthansa mobile boarding pass.

    Returns *enrichment* records, not flights: each names the leg it belongs to
    by ``flight_number`` plus ``departure_date`` so the caller can find the
    stored flight, and carries only the fields this email adds. An airline
    module exposing this function opts into the pipeline's boarding-pass
    enrichment step; one that does not is simply skipped.
    """
    html = getattr(email_msg, "html_body", None)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)

    details = []
    for m in _boarding_pass_flight_date_re.finditer(text):
        fn = normalize_fn(m.group(1))
        dep_date = parse_flight_date(m.group(2))
        if not fn or not dep_date:
            continue
        # Scope every field to this leg's own block so a second boarding pass
        # further down the mail cannot donate its seat to the first.
        block = text[m.end() : m.end() + 1200]
        record = {
            "flight_number": fn,
            "departure_date": dep_date.isoformat(),
            "departure_airport": m.group(3),
            "arrival_airport": m.group(4),
        }
        for key, pattern in (
            ("seat", _bp_seat_re),
            ("gate", _bp_gate_re),
            ("departure_terminal", _bp_terminal_re),
            ("cabin_class", _bp_cabin_re),
        ):
            found = pattern.search(block)
            if found:
                record[key] = found.group(1).strip()
        ref_m = _boarding_pass_booking_ref_re.search(block)
        if ref_m:
            record["booking_reference"] = ref_m.group(1)
        pax_m = _bp_passenger_re.search(text[: m.start()])
        if pax_m:
            record["passenger_name"] = pax_m.group(1).strip()
        details.append(record)
    return details


def _extract_f4(text: str, rule, booking_ref: str) -> list[dict]:
    """Format 4: Lufthansa check-in available (your.lufthansa-group.com)."""
    flights = []
    for m in _checkin_leg_re.finditer(text):
        dep_date = _parse_ddmmyyyy(m.group(4))
        if not dep_date:
            continue
        dep_dt = _build_datetime(dep_date, m.group(5))
        arr_dt = _build_datetime(dep_date, m.group(6))
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)
        flight = make_flight_dict(
            rule,
            normalize_fn(m.group(3)),
            m.group(1),
            m.group(2),
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


def extract_bs4(html: str, rule, email_msg) -> list[dict]:
    """Extract flights from a Lufthansa HTML email (tries all 4 formats)."""
    soup = BeautifulSoup(html, "lxml")
    text = _get_text(soup)  # space-separated (format 2)
    text_nl = soup.get_text(separator="\n", strip=True)  # newline-separated (1, 3, 4)
    booking_ref = extract_booking_reference(text, email_msg.subject or "")

    # The itinerary table is tried first: it is the richest format (per-leg
    # terminals, explicit "+1" arrivals, cancelled-leg status) and the only one
    # that reads non-LH marketing carriers on a Lufthansa booking.
    # It reads html_to_text output rather than the raw BS4 text the older formats
    # use: Lufthansa peppers this template with zero-width spaces ("1​4:0​0 h"),
    # which html_to_text strips and a per-line regex otherwise cannot survive.
    flights = _extract_itinerary(html_to_text(html), rule, booking_ref)
    if flights:
        passenger = extract_passenger(text)
        if passenger:
            for f in flights:
                f["passenger_name"] = f.get("passenger_name") or passenger
        return flights

    flights = _extract_f1(text, rule, booking_ref)
    if flights:
        return flights

    for extractor in (_extract_f3, _extract_f4):
        flights = extractor(text_nl, rule, booking_ref)
        if flights:
            return flights

    return []


def extract(email_msg, rule) -> list[dict]:
    """Unified entry point: try HTML (BS4) only."""
    if email_msg.html_body:
        return extract_bs4(email_msg.html_body, rule, email_msg)
    return []


# ---------------------------------------------------------------------------
# Cancellations
# ---------------------------------------------------------------------------

# "we had to cancel your booking" is Lufthansa's own wording on the cancellation
# confirmation; the German and Portuguese stems cover the same mail in the other
# locales the rest of this module already handles (`_itin_cancelled_re`).
_lh_cancelled_re = re.compile(
    r"had\s+to\s+cancel\s+your\s+booking"
    r"|cancellation\s+confirmation"
    r"|stornierungsbest[äa]tigung"
    r"|confirma[çc][ãa]o\s+de\s+cancelamento",
    re.IGNORECASE,
)


def extract_cancellations(email_msg) -> list[dict]:
    """Lufthansa cancels a whole booking and names it by its booking code.

    The mail prints "Lufthansa booking code: PKMV4L" and the passengers, and
    lists no legs at all — so like SAS this is a booking-level record. Note the
    itinerary-level `Estatuto: Cancelada` marker `extract` already honours is a
    different thing: that one appears on a *schedule change* that reprints the
    dropped leg beside the surviving ones, and is handled by not extracting it.
    """
    text = get_email_text(email_msg)
    subject = email_msg.subject or ""
    if not _lh_cancelled_re.search(f"{subject}\n{text}"):
        return []
    record = booking_cancellation(extract_booking_reference(text, subject))
    return [record] if record else []
