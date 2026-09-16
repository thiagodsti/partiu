"""Airline-independent parser for GDS electronic-ticket receipts (ITR / ITR-EMD).

Amadeus, Sabre and Travelport issue the passenger receipt for a ticket in a
handful of shared layouts that the ticketing airline barely customises, so one
parser here covers many carriers instead of a per-airline regex that breaks the
moment a leg happens to have no terminal number (which is exactly how the
hand-written TAP e-ticket pattern silently stopped matching).

Two renderings of the same document are supported, because the itinerary
arrives either as HTML or as a PDF attachment depending on the carrier:

**Table layout** — the itinerary is an HTML table, one row per leg::

    From                      To                     Flight  Departure         Arrival
    STOCKHOLM ARLANDA         LISBON AIRPORT         TP781   14:20 22Dec2026   17:55 22Dec2026
    Terminal / Terminal: 2    Terminal / Terminal: 1

**Compact layout** — one text line per leg, as rendered in the PDF receipt.
Here the HTML part is only a cover note and carries no itinerary at all::

    Flight/Date          Route                          Departure Arrival
    AF 871 / 12NOV       Cape Town - Paris CDG          07:55     19:15
    AF 1462 / 12NOV      Paris CDG - Stockholm Arlanda  21:00     23:40  Terminal 2F

Three things make this parser trustworthy where the generic line scanner is not:

* It reads **structure** — a table cell's column, or a single line matched as a
  whole — rather than guessing what a nearby line might mean.  The line scanner
  had no way to tell the "NVA"/"NVB" *not-valid-before/after* labels from an
  airport code; NVA is Neiva, Colombia.
* It prefers **real IATA codes already present in the email**.  These receipts
  repeat the routing in the baggage-allowance sections as bare airport pairs
  ("ARNLIS LISFLN FLNGRU"), which is ground truth that needs no city-name
  guessing at all; city names are only resolved when that fails.
* It **declines** rather than guesses: no receipt marker, or no leg matching a
  known layout, and it returns [] so the caller's other strategies still run.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from datetime import date as date_type

from ..utils import validate_flight_number
from .shared import (
    _build_datetime,
    enrich_flights,
    fix_overnight,
    get_ref_year,
    make_flight_dict,
    parse_date,
    resolve_iata,
)

logger = logging.getLogger(__name__)

# Markers identifying a GDS ticket receipt, in the languages these are issued in.
_RECEIPT_MARKERS = (
    "electronic ticket receipt",
    "recibo de bilhete",
    "recibo de billete",
    "itr-emd",
    "e-ticket receipt",
    "electronic ticket itinerary",
    "billet electronique",
    "billet électronique",
    "elektronisches ticket",
    "ricevuta biglietto elettronico",
    "passenger itinerary receipt",
)

_FLIGHT_CELL_RE = re.compile(r"^([A-Z]{1,3})\s?(\d{1,4})$")
# "14:20 22Dec2026" — a time and a compact date in one cell, either order.
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
_COMPACT_DATE_RE = re.compile(r"\b(\d{1,2}[A-Za-z]{3}\d{2,4})\b")
# "Terminal / Terminal: 2" — the label is repeated in two languages, so anchor on
# the colon and take what follows it, not whatever word trails the first "Terminal".
_TERMINAL_RE = re.compile(r"Terminal\s*:\s*([A-Za-z0-9-]{1,4})\b", re.IGNORECASE)
_TERMINAL_LABEL_RE = re.compile(r"\bTerminal\b.*$", re.IGNORECASE | re.DOTALL)
# Bare airport pairs as they appear in the baggage sections: "ARNLIS", "FLNGRU"
_IATA_PAIR_RE = re.compile(r"\b([A-Z]{3})([A-Z]{3})\b")
# The same pairs when they stand alone on a line, or head one ("ARNLIS: MAX 1PC").
# _IATA_PAIR_RE also matches any six-capital word — "LISBON" is (LIS, BON) and
# BON is Bonaire — and on the columnar layout that phantom sat beside the real
# "LISARN" and made the corroboration ambiguous, so the leg was dropped. A pair
# on its own line is the baggage block's restatement and nothing else.
_STANDALONE_PAIR_RE = re.compile(r"^[^\S\n]*([A-Z]{3})([A-Z]{3})[^\S\n]*(?::|$)", re.MULTILINE)

# Compact layout, one line per leg:
#   "AF 871 / 12NOV Cape Town - Paris CDG 07:55 19:15 07:15 1PC"
# Anchored on the two times at the end, so the route can contain spaces
# ("Stockholm Arlanda") without the city names running into the timings.
_COMPACT_LEG_RE = re.compile(
    r"^[^\S\n]*(?P<code>[A-Z]{1,3})[^\S\n]*(?P<num>\d{1,4})[^\S\n]*/[^\S\n]*"
    r"(?P<date>\d{1,2}[A-Za-z]{3}\d{0,4})[^\S\n]+"
    r"(?P<dep>[^\d\n][^\n]*?)[^\S\n]+-[^\S\n]+(?P<arr>[^\n]*?)"
    r"[^\S\n]+(?P<dep_time>\d{1,2}:\d{2})[^\S\n]+(?P<arr_time>\d{1,2}:\d{2})"
    r"(?P<tail>[^\n]*)$",
    re.MULTILINE,
)
# "Terminal 2F" trailing a compact leg line — belongs to the *arrival* airport.
_COMPACT_TERMINAL_RE = re.compile(r"\bTerminal\s+([A-Za-z0-9]{1,3})\b", re.IGNORECASE)

# Amadeus fixed-column layout — the classic ITR as plain text, one departure
# line per leg with the arrival on the next line and the terminals between:
#
#   FROM /TO        FLIGHT  CL DATE  DEP      FARE BASIS    NVB   NVA   BAG ST
#   STOCKHOLM ARLAN TP 783  T  10NOV 1905     TF0DSC02                  0PC OK
#   TERMINAL:5
#   LISBON AIRPORT                   ARRIVAL TIME: 2235     ARRIVAL DATE: 10NOV
#   TERMINAL:1         LATEST CHECK-IN:1820
#
# Place names are truncated to the column width ("STOCKHOLM ARLAN"), so name
# resolution is expected to fail on some of them; the baggage block's bare pairs
# ("ARNLIS") are what settles those, through _pick_corroborated_route. Times
# are four bare digits. Dates carry no year, like the compact layout.
_COLUMNAR_LEG_RE = re.compile(
    r"^[^\S\n]*(?P<dep>[A-Z][A-Z0-9 .'/-]{1,24}?)[^\S\n]+"
    r"(?P<code>[A-Z0-9]{2})[^\S\n]?(?P<num>\d{1,4})[^\S\n]+"
    r"(?P<cl>[A-Z])[^\S\n]+(?P<date>\d{1,2}[A-Z]{3})[^\S\n]+(?P<time>\d{4})\b[^\n]*\n"
    r"(?:[^\S\n]*TERMINAL:[^\S\n]*(?P<dep_term>[A-Za-z0-9]{1,4})[^\n]*\n)?"
    r"[^\S\n]*(?P<arr>[A-Z][A-Z0-9 .'/-]{1,24}?)[^\S\n]+ARRIVAL TIME:[^\S\n]*"
    r"(?P<arr_time>\d{4})\b"
    r"(?:[^\S\n]+ARRIVAL DATE:[^\S\n]*(?P<arr_date>\d{1,2}[A-Z]{3}))?[^\n]*\n"
    r"(?:[^\S\n]*TERMINAL:[^\S\n]*(?P<arr_term>[A-Za-z0-9]{1,4}))?",
    re.MULTILINE,
)


class _SimpleRule:
    """Minimal rule-like object inferred from a flight number's airline code."""

    def __init__(self, airline_code: str) -> None:
        self.airline_code = airline_code
        self.airline_name = airline_code


def looks_like_gds_eticket(text: str) -> bool:
    """True when *text* carries a GDS ticket-receipt marker."""
    lowered = text.lower()
    return any(marker in lowered for marker in _RECEIPT_MARKERS)


# ---------------------------------------------------------------------------
# Routing corroboration
# ---------------------------------------------------------------------------


def collect_iata_pairs(text: str) -> list[tuple[str, str]]:
    """Collect ordered origin/destination pairs written as bare IATA codes.

    GDS receipts restate the routing in the baggage-allowance blocks as
    concatenated pairs ("ARNLIS", "LISFLN", …).  These are the airline's own
    codes for the exact legs on the ticket, so when they line up with the
    itinerary table they beat anything city-name resolution could infer.

    Duplicates are preserved in order; the caller decides how to line them up.
    """
    pairs: list[tuple[str, str]] = []
    for match in _IATA_PAIR_RE.finditer(text):
        dep, arr = match.group(1), match.group(2)
        if dep != arr:
            pairs.append((dep, arr))
    return pairs


def collect_standalone_iata_pairs(text: str) -> list[tuple[str, str]]:
    """Like ``collect_iata_pairs`` but only pairs standing alone on a line."""
    return [
        (m.group(1), m.group(2))
        for m in _STANDALONE_PAIR_RE.finditer(text)
        if m.group(1) != m.group(2)
    ]


def _pick_corroborated_route(dep: str, arr: str, pairs: list[tuple[str, str]]) -> tuple[str, str]:
    """Return the IATA pair from *pairs* matching a half-resolved route.

    Used when city-name resolution produced only one end of a leg (or neither).
    A pair is only accepted when it is unambiguous — exactly one candidate —
    so a corroborating source can fill a gap but never silently overrule
    a confident city-name match.
    """
    if dep and arr:
        return dep, arr
    if dep:
        candidates = {p for p in pairs if p[0] == dep}
    elif arr:
        candidates = {p for p in pairs if p[1] == arr}
    else:
        return dep, arr
    if len(candidates) == 1:
        return candidates.pop()
    return dep, arr


# ---------------------------------------------------------------------------
# Cell-level helpers
# ---------------------------------------------------------------------------


def _airport_from_cell(cell: str) -> tuple[str, str]:
    """Split a From/To cell into (IATA code, terminal).

    The cell reads like "STOCKHOLM ARLANDA Terminal / Terminal: 2", so the
    terminal suffix is stripped before the place name is resolved — otherwise
    the word "Terminal" becomes part of the name being looked up.
    """
    terminal = ""
    m = _TERMINAL_RE.search(cell)
    if m:
        terminal = m.group(1)
    place = _TERMINAL_LABEL_RE.sub("", cell).strip(" /:-,")
    # An explicit code in the cell always wins over the prose name
    paren = re.search(r"\(([A-Z]{3})\)", place)
    if paren:
        return paren.group(1), terminal
    return resolve_iata(place.strip()), terminal


def _resolve_receipt_date(token: str, ref_date) -> date_type | None:
    """Parse a receipt date token, resolving a missing year *forwards*.

    A ticket receipt is issued when the ticket is bought, so its flights are
    always on or after the issue date. Injecting the email's year into a
    year-less token therefore lands a year early whenever the booking crosses
    New Year: a receipt sent 06 Dec 2024 listing "28OCT" means October 2025.

    This is safe here in a way it would not be generally — the caller has
    already established the email *is* a ticket receipt, so travel-after-issue
    holds. Post-trip emails about past flights never reach this code.
    """
    has_explicit_year = bool(re.search(r"\d{1,2}[A-Za-z]{3}\d{2,4}$", token.strip()))
    ref_year = ref_date.year if ref_date else datetime.now(tz=UTC).year
    parsed = parse_date(token, ref_year)
    if not parsed or has_explicit_year or not ref_date:
        return parsed

    # One day of slack absorbs timezone differences around the issue date.
    if parsed >= ref_date.date() - timedelta(days=1):
        return parsed
    try:
        return parsed.replace(year=parsed.year + 1)
    except ValueError:  # 29 Feb in a non-leap year
        return parsed


def _datetime_from_cell(cell: str, ref_year: int) -> tuple[str, date_type | None]:
    """Pull (HH:MM, date) out of a Departure/Arrival cell."""
    time_m = _TIME_RE.search(cell)
    date_m = _COMPACT_DATE_RE.search(cell)
    time_str = time_m.group(1) if time_m else ""
    the_date = parse_date(date_m.group(1), ref_year) if date_m else None
    return time_str, the_date


def _cells_of_row(row) -> list[str]:
    """Non-empty visible cell texts of a table row (direct children only)."""
    cells = row.find_all(["td", "th"], recursive=False)
    return [t for c in cells if (t := c.get_text(" ", strip=True))]


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------


def _legs_from_html(html: str, ref_year: int) -> list[dict]:
    """Extract raw leg records from the itinerary table of a GDS receipt.

    A leg row is recognised by shape, not position: it holds exactly one
    flight-number cell, and the two cells before it are the From/To places
    while the two after it are the Departure/Arrival datetimes.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    legs: list[dict] = []

    for row in soup.find_all("tr"):
        cells = _cells_of_row(row)
        matches = [(i, m) for i, c in enumerate(cells) if (m := _FLIGHT_CELL_RE.match(c))]
        if len(matches) != 1:
            continue
        idx, flight_match = matches[0]
        # Need From/To before it and Departure/Arrival after it
        if idx < 2 or idx + 2 >= len(cells):
            continue

        code, number = flight_match.groups()
        dep_iata, dep_terminal = _airport_from_cell(cells[idx - 2])
        arr_iata, arr_terminal = _airport_from_cell(cells[idx - 1])
        dep_time, dep_date = _datetime_from_cell(cells[idx + 1], ref_year)
        arr_time, arr_date = _datetime_from_cell(cells[idx + 2], ref_year)

        legs.append(
            {
                "flight_number": f"{code}{number}",
                "dep_iata": dep_iata,
                "arr_iata": arr_iata,
                "dep_terminal": dep_terminal,
                "arr_terminal": arr_terminal,
                "dep_time": dep_time,
                "dep_date": dep_date,
                "arr_time": arr_time,
                "arr_date": arr_date,
            }
        )
    return legs


def _legs_from_text(text: str, ref_date) -> list[dict]:
    """Extract raw leg records from the compact one-line-per-leg layout.

    Used for receipts delivered as a PDF attachment, where the HTML part is
    just a cover note. PDF text is already appended to ``EmailMessage.body`` by
    ``get_email_body_and_html``, so there is nothing to re-extract here.

    This layout prints no year on the leg dates, hence ``_resolve_receipt_date``.
    Only the departure date is printed per leg; the arrival date is inferred by
    ``fix_overnight`` from the times, exactly as the table layout does when a
    receipt prints the date only once.
    """
    legs: list[dict] = []
    for m in _COMPACT_LEG_RE.finditer(text):
        dep_place = m.group("dep").strip(" .,-")
        arr_place = m.group("arr").strip(" .,-")
        if not dep_place or not arr_place:
            continue

        dep_date = _resolve_receipt_date(m.group("date"), ref_date)
        if not dep_date:
            continue

        # A trailing "Terminal 2F" describes the arrival airport on this layout.
        terminal_match = _COMPACT_TERMINAL_RE.search(m.group("tail") or "")

        legs.append(
            {
                "flight_number": f"{m.group('code')}{m.group('num')}",
                "dep_iata": resolve_iata(dep_place),
                "arr_iata": resolve_iata(arr_place),
                "dep_terminal": "",
                "arr_terminal": terminal_match.group(1) if terminal_match else "",
                "dep_time": m.group("dep_time"),
                "dep_date": dep_date,
                "arr_time": m.group("arr_time"),
                "arr_date": None,  # same day unless the times wrap past midnight
            }
        )
    return legs


def _legs_from_columnar_text(text: str, ref_date) -> list[dict]:
    """Extract raw leg records from the Amadeus fixed-column layout.

    The same receipt is often present twice in one email — the fixed-width
    text and a whitespace-collapsed copy of the HTML ``<pre>`` — so legs are
    deduplicated on (flight number, date, departure time).
    """
    legs: list[dict] = []
    seen: set[tuple[str, date_type | None, str]] = set()
    for m in _COLUMNAR_LEG_RE.finditer(text):
        dep_date = _resolve_receipt_date(m.group("date"), ref_date)
        if not dep_date:
            continue
        arr_token = m.group("arr_date")
        arr_date = _resolve_receipt_date(arr_token, ref_date) if arr_token else None
        fn = f"{m.group('code')}{m.group('num')}"
        dep_time = _hhmm(m.group("time"))
        key = (fn, dep_date, dep_time)
        if key in seen:
            continue
        seen.add(key)
        legs.append(
            {
                "flight_number": fn,
                "dep_iata": resolve_iata(m.group("dep").strip()),
                "arr_iata": resolve_iata(m.group("arr").strip()),
                "dep_terminal": m.group("dep_term") or "",
                "arr_terminal": m.group("arr_term") or "",
                "dep_time": dep_time,
                "dep_date": dep_date,
                "arr_time": _hhmm(m.group("arr_time")),
                "arr_date": arr_date,
            }
        )
    return legs


def _hhmm(four_digits: str) -> str:
    """ "1905" → "19:05"."""
    return f"{four_digits[:2]}:{four_digits[2:]}"


def _pdf_text(email_msg) -> str:
    """Text of any PDF attachments, extracted defensively.

    ``get_email_body_and_html`` normally folds this into ``body`` already, but
    not every caller builds an EmailMessage that way, and the compact layout
    lives *only* in the PDF — so this parser fetches it rather than depending on
    how it was constructed.
    """
    if not email_msg.pdf_attachments:
        return ""
    try:
        return email_msg.get_pdf_text() or ""
    except Exception:
        logger.debug("Could not read PDF text from %s", email_msg.message_id, exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_gds_eticket(email_msg, rule=None) -> list[dict]:
    """Extract flights from a GDS electronic-ticket receipt.

    Returns [] when the email is not a ticket receipt or no known layout
    matches, leaving the caller's other strategies untouched.
    """
    html = email_msg.html_body or ""
    body = email_msg.body or ""

    ref_year = get_ref_year(email_msg)
    # Table layout first — it prints an explicit arrival date per leg, so it
    # carries strictly more information than the compact one.
    legs: list[dict] = []
    if html and looks_like_gds_eticket(html):
        legs = _legs_from_html(html, ref_year)

    text = body
    if not legs:
        # The compact layout lives in the PDF, whose text may or may not already
        # be part of `body` depending on how the EmailMessage was built.
        pdf = _pdf_text(email_msg)
        if pdf and pdf not in text:
            text = f"{text}\n{pdf}" if text else pdf
        if looks_like_gds_eticket(text) or looks_like_gds_eticket(html):
            legs = _legs_from_text(text, email_msg.date)
            if not legs:
                legs = _legs_from_columnar_text(text, email_msg.date)

    if not legs:
        return []

    # Ground-truth routing restated elsewhere in the receipt. Pairs on their
    # own line are tried first; the looser scan only when those settle nothing.
    standalone_pairs = collect_standalone_iata_pairs(text)
    pairs = collect_iata_pairs(text)

    flights: list[dict] = []
    for leg in legs:
        dep_iata, arr_iata = _pick_corroborated_route(
            leg["dep_iata"], leg["arr_iata"], standalone_pairs
        )
        if not dep_iata or not arr_iata:
            dep_iata, arr_iata = _pick_corroborated_route(dep_iata, arr_iata, pairs)
        if not dep_iata or not arr_iata:
            logger.debug(
                "GDS e-ticket: unresolved route for %s (%r -> %r)",
                leg["flight_number"],
                leg["dep_iata"],
                leg["arr_iata"],
            )
            continue

        fn = leg["flight_number"]
        if not validate_flight_number(fn):
            continue

        dep_dt = _build_datetime(leg["dep_date"], leg["dep_time"])
        # Arrival dates are printed per leg, but fall back to the departure date
        # for layouts that only print it once.
        arr_dt = _build_datetime(leg["arr_date"] or leg["dep_date"], leg["arr_time"])
        if not dep_dt or not arr_dt:
            continue
        arr_dt = fix_overnight(dep_dt, arr_dt)

        effective_rule = rule if rule is not None else _SimpleRule(fn[:2])
        flight = make_flight_dict(effective_rule, fn, dep_iata, arr_iata, dep_dt, arr_dt)
        if not flight:
            continue
        flight["departure_terminal"] = leg["dep_terminal"]
        flight["arrival_terminal"] = leg["arr_terminal"]
        flights.append(flight)

    if flights:
        logger.info(
            "GDS e-ticket parser extracted %d leg(s) from %s",
            len(flights),
            email_msg.message_id,
        )
    # Enrich from `text`, not `body`: on a PDF-only receipt the booking
    # reference and passenger name are in the attachment, not the cover note.
    return enrich_flights(flights, text, email_msg.subject)
