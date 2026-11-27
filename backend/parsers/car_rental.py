"""Car-rental confirmations — Hertz, Sixt, Europcar and Booking.com.

Structural, per-vendor, and gated on the sender, exactly like an airline rule.
There is deliberately **no generic tier** here for the same reason
`parsers/generic_html.py` was deleted: a rental mail is mostly price breakdown
and terms, and anchoring on "a date near the word pickup" across an unknown
template invents bookings. A vendor this module does not know returns nothing,
and the LLM fallback is welcome to it.

Booking.com is the one broker here: its ``cars.booking.com`` confirmation is
HTML rather than the plain-text layout the three vendors use, and the supplier
is a field in the mail ("Rental company") rather than the sender. Its dates and
places are still structural, so it belongs in this reader rather than in a
proximity tier.

The three direct vendors print the same five facts in their own layouts, all
readable from the **plain-text** part:

  Hertz     Confirmation / K78806710D9 ... Pickup Location / <place> ...
            Pickup Date & Time / Fri, Mar 29, 2024 at 09:30 AM
  Sixt      Reservation: / 9710114165 ... Pickup at <place> /
            Friday, Mar 29, 2024 at 1:30 pm ... Return at <place> / ...
  Europcar  Your booking or reservation number is: / 1106320078 ...
            Pick-up / TRAPANI AIRPORT / 8/24/19 8:00 AM ... Return / ...

Booking.com puts the same facts in its HTML part, with ``Rental company``
naming the supplier. Two of the three measured direct-vendor bookings are
**one-way** (Munich→Vienna, Trapani→Catania), which is why a rental carries two
places rather than one.

Times come back as *naive local* ISO strings ("2024-03-29T09:30"), matching what
`CarRentalService` expects: it derives each counter's zone from the geocoded
coordinates and converts, the same contract `stays_import` has. This module never
guesses a timezone — the counter's own address is the only evidence, and
resolving it is the importer's job.
"""

import logging
import re
from datetime import date as date_type
from datetime import datetime

from .engine import candidate_senders, candidate_subjects, parse_flight_date
from .shared import html_to_text

logger = logging.getLogger(__name__)

__all__ = [
    "CAR_RENTAL_SENDER_PATTERNS",
    "VENDOR_SENDER_PATTERNS",
    "extract_car_rentals",
    "is_booking_com_car_sender",
    "is_car_rental_sender",
]

# Which vendor a sender is. Matched against the sender the same way an airline
# rule's `sender_pattern` is, and the only gate on this module running.
VENDOR_SENDER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Hertz", r"(@hertz\.com|@emails\.hertz\.com|\.hertz\.com)"),
    ("Sixt", r"(@sixt\.com|@e\.sixt\.com|\.sixt\.com)"),
    ("Europcar", r"(@europcar\.com|\.europcar\.com)"),
)
_BOOKING_CAR_SENDER_RE = re.compile(r"@cars\.booking\.com\b", re.IGNORECASE)
# The same senders, as plain patterns for the IMAP fetch filter. A confirmation
# can say "car rental ... is confirmed" — no flight word, no airline sender — so
# without these the parser never sees the mail on a sync. Fetching is safe: this
# module decides for itself whether the message is a rental it can read.
CAR_RENTAL_SENDER_PATTERNS: tuple[str, ...] = tuple(
    pattern for _, pattern in VENDOR_SENDER_PATTERNS
) + (_BOOKING_CAR_SENDER_RE.pattern,)
# The subject arrives RFC2047-decoded and can carry a fold between "Airport"
# and "is", so the match has to cross a newline.
_BOOKING_CAR_CONFIRMED_RE = re.compile(
    r"\bcar (?:hire|rental)\b.*\bconfirmed\b", re.IGNORECASE | re.DOTALL
)
_BOOKING_CAR_CANCELLED_RE = re.compile(r"\bcancel", re.IGNORECASE)

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", re.IGNORECASE)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_NAMED_DATE_RE = re.compile(r"\b\d{1,2}\s+[^\W\d_]+\.?\s+\d{4}\b")


def is_car_rental_sender(sender: str) -> str:
    """Return the vendor name for this sender, or "" when it is not a rental
    company we can read."""
    for vendor, pattern in VENDOR_SENDER_PATTERNS:
        if re.search(pattern, sender or "", re.IGNORECASE):
            return vendor
    return ""


def is_booking_com_car_sender(sender: str) -> bool:
    """Booking.com sends car confirmations from ``cars.booking.com``, not from
    the supplier's own domain — the supplier is a field in the mail."""
    return bool(_BOOKING_CAR_SENDER_RE.search(sender or ""))


def _parse_time(text: str) -> tuple[int, int] | None:
    """Read "09:30 AM", "1:30 pm" or a bare "18:45" into (hour, minute)."""
    m = _TIME_RE.search(text)
    if m:
        hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        if hour == 12:
            hour = 0
        if meridiem == "p":
            hour += 12
        return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    return (hour, minute) if hour < 24 and minute < 60 else None


def _iso_local(day: date_type, clock: tuple[int, int]) -> str:
    """The naive-local ISO string the rental service parses."""
    return datetime(day.year, day.month, day.day, clock[0], clock[1]).isoformat(timespec="minutes")


def _numeric_dates_month_first(raw_dates: list[str]) -> bool:
    """Whether a batch of ``d/m/y``-shaped dates is month-first.

    Europcar prints "8/24/19" with no month name to settle the order, and
    guessing wrong moves a booking by months rather than failing visibly. The
    two dates in one mail come from one template, so a single unambiguous
    component decides both: a middle component above 12 can only be a day
    (month-first), a leading component above 12 can only be a day (day-first).

    With neither settled — "5/6/19" — this falls back to month-first, which is
    what the measured Europcar mail uses and what its English wording
    ("Pick-up", "Duration", "day") goes with. That fallback is the one guess in
    this module, so it is logged.
    """
    for raw in raw_dates:
        m = _NUMERIC_DATE_RE.search(raw)
        if not m:
            continue
        first, second = int(m.group(1)), int(m.group(2))
        if second > 12:
            return True
        if first > 12:
            return False
    logger.info("Car rental: ambiguous numeric dates %r — assuming month-first", raw_dates)
    return True


def _parse_numeric_date(raw: str, month_first: bool) -> date_type | None:
    m = _NUMERIC_DATE_RE.search(raw)
    if not m:
        return None
    a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    month, day = (a, b) if month_first else (b, a)
    try:
        return date_type(year, month, day)
    except ValueError:
        return None


def _lines(text: str) -> list[str]:
    """Non-empty, stripped lines. Every vendor here puts each field on its own
    line in the text part, so the layouts are walked line by line rather than
    matched with one regex — the filler between fields is independently optional
    in all three, and a regex with optional filler drifts onto the next block's
    values as soon as one piece is missing (the trap `pegasus` documents)."""
    return [line.strip() for line in (text or "").split("\n") if line.strip()]


def _find_index(lines: list[str], pattern: str, start: int = 0) -> int:
    rx = re.compile(pattern, re.IGNORECASE)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    return -1


def _first_date_after(
    lines: list[str], index: int, window: int = 8
) -> tuple[date_type, str] | None:
    """The first line after ``index`` that parses as a date with a month name,
    plus that line (the time usually sits on it too)."""
    for line in lines[index + 1 : index + 1 + window]:
        # Strip a trailing " at 09:30 AM" before asking for the date.
        candidate = re.split(r"\s+at\s+", line, maxsplit=1)[0].strip().rstrip(",")
        parsed = parse_flight_date(candidate)
        if parsed:
            return parsed, line
    return None


def _first_place_after(lines: list[str], index: int, window: int = 4) -> str:
    """The first line after ``index`` that reads like a place name rather than a
    label, a country code or a postcode."""
    for line in lines[index + 1 : index + 1 + window]:
        if len(line) < 3 or line.isdigit():
            continue
        if re.fullmatch(r"[A-Z]{2},?", line):  # the bare "AT" country line Hertz prints
            continue
        if re.search(r"date\s*&?\s*time|location hours|station details", line, re.IGNORECASE):
            continue
        return line.rstrip(",")
    return ""


# ---------------------------------------------------------------------------
# Booking.com (the broker, not the supplier)
# ---------------------------------------------------------------------------


def _booking_label_value(lines: list[str], label: str) -> str:
    """The line under a label like ``Confirmation:`` or ``Rental company``."""
    idx = _find_index(lines, rf"^{re.escape(label)}:?$")
    return lines[idx + 1] if 0 <= idx < len(lines) - 1 else ""


def _booking_datetime(line: str) -> str:
    """Read "Saturday, 19 December 2026 11:30" at a counter's own wall clock."""
    match = _NAMED_DATE_RE.search(line)
    if not match:
        return ""
    day = parse_flight_date(match.group(0))
    clock = _parse_time(line)
    if not day or not clock:
        return ""
    return _iso_local(day, clock)


def _extract_booking_com(lines: list[str]) -> dict | None:
    """Read the HTML rendering Booking.com uses for a broker car confirmation.

    Unlike the three vendors, this mail puts the supplier in its own labelled
    field and its facts in the HTML part: date and time, then place, directly
    under ``Pick-up`` / ``Drop-off``. The place may be a short airport name at
    one end and the full counter address at the other (one-way hires exist);
    both are printed, so neither is guessed.
    """
    pickup_at = _find_index(lines, r"^Pick-up$")
    dropoff_at = _find_index(lines, r"^Drop-off$")
    if pickup_at < 0 or dropoff_at < 0:
        return None
    if pickup_at + 2 >= len(lines) or dropoff_at + 2 >= len(lines):
        return None

    pickup_at_when, dropoff_at_when = lines[pickup_at + 1], lines[dropoff_at + 1]
    pickup_place, dropoff_place = lines[pickup_at + 2], lines[dropoff_at + 2]
    pickup_datetime, dropoff_datetime = (
        _booking_datetime(pickup_at_when),
        _booking_datetime(dropoff_at_when),
    )
    if not pickup_datetime or not dropoff_datetime or not pickup_place or not dropoff_place:
        return None

    vendor = _booking_label_value(lines, "Rental company")
    if not vendor:
        return None
    ref = _booking_label_value(lines, "Confirmation")
    if not re.fullmatch(r"[A-Z0-9]{6,20}", ref or "", re.IGNORECASE):
        # A label with no value must not fall through to whatever line follows —
        # the next one is often a PIN or a phone number in these mails.
        ref = ""
    vehicle = next(
        (line for line in lines[:pickup_at] if re.search(r"\bor similar\b", line, re.IGNORECASE)),
        "",
    )

    return {
        "vendor": vendor,
        "booking_reference": ref,
        "pickup_place": pickup_place,
        "pickup_datetime": pickup_datetime,
        "dropoff_place": dropoff_place,
        "dropoff_datetime": dropoff_datetime,
        "vehicle": vehicle,
        "driver_name": _booking_label_value(lines, "Driver details"),
    }


# ---------------------------------------------------------------------------
# Hertz
# ---------------------------------------------------------------------------


def _extract_hertz(lines: list[str]) -> dict | None:
    pickup_at = _find_index(lines, r"^Pickup\s+Date\s*&?\s*Time$")
    dropoff_at = _find_index(lines, r"^Drop-?off\s+Date\s*&?\s*Time$")
    pickup_loc = _find_index(lines, r"^Pickup\s+Location$")
    dropoff_loc = _find_index(lines, r"^Drop-?off\s+Location$")
    if min(pickup_at, dropoff_at, pickup_loc, dropoff_loc) < 0:
        return None

    pickup = _first_date_after(lines, pickup_at)
    dropoff = _first_date_after(lines, dropoff_at)
    if not pickup or not dropoff:
        return None
    pickup_time = _parse_time(pickup[1])
    dropoff_time = _parse_time(dropoff[1])
    if not pickup_time or not dropoff_time:
        return None

    ref_at = _find_index(lines, r"^Confirmation$")
    booking_reference = ""
    if ref_at >= 0 and ref_at + 1 < len(lines):
        candidate = lines[ref_at + 1]
        if re.fullmatch(r"[A-Z0-9]{6,15}", candidate):
            booking_reference = candidate

    return {
        "booking_reference": booking_reference,
        "pickup_place": _first_place_after(lines, pickup_loc),
        "pickup_datetime": _iso_local(pickup[0], pickup_time),
        "dropoff_place": _first_place_after(lines, dropoff_loc),
        "dropoff_datetime": _iso_local(dropoff[0], dropoff_time),
        "vehicle": _hertz_vehicle(lines),
    }


def _hertz_vehicle(lines: list[str]) -> str:
    """Hertz prints the class, then the model, then "or similar" on three lines.

    The model line carries a leading group code — "(A) Fiat 500" — which is
    Hertz's own vehicle class and means nothing to the traveller, so it is cut.
    """
    idx = _find_index(lines, r"^or similar$")
    if idx < 1:
        return ""
    model = re.sub(r"^\([A-Z]\)\s*", "", lines[idx - 1]).strip()
    return f"{model} or similar" if model else ""


# ---------------------------------------------------------------------------
# Sixt
# ---------------------------------------------------------------------------

_SIXT_PICKUP_RE = re.compile(r"^Pick-?up\s+at\s+(.+)$", re.IGNORECASE)
_SIXT_RETURN_RE = re.compile(r"^Return\s+at\s+(.+)$", re.IGNORECASE)


def _extract_sixt(lines: list[str]) -> dict | None:
    pickup_at = dropoff_at = -1
    pickup_place = dropoff_place = ""
    for i, line in enumerate(lines):
        if (m := _SIXT_PICKUP_RE.match(line)) and pickup_at < 0:
            pickup_at, pickup_place = i, m.group(1)
        elif (m := _SIXT_RETURN_RE.match(line)) and dropoff_at < 0:
            dropoff_at, dropoff_place = i, m.group(1)
    if pickup_at < 0 or dropoff_at < 0:
        return None

    pickup = _first_date_after(lines, pickup_at)
    dropoff = _first_date_after(lines, dropoff_at)
    if not pickup or not dropoff:
        return None
    pickup_time = _parse_time(pickup[1])
    dropoff_time = _parse_time(dropoff[1])
    if not pickup_time or not dropoff_time:
        return None

    ref_at = _find_index(lines, r"^Reservation:?$")
    booking_reference = ""
    if ref_at >= 0 and ref_at + 1 < len(lines) and re.fullmatch(r"\d{6,15}", lines[ref_at + 1]):
        booking_reference = lines[ref_at + 1]

    vehicle_at = _find_index(lines, r"^Vehicle category$")
    vehicle = lines[vehicle_at + 1] if 0 <= vehicle_at < len(lines) - 1 else ""

    return {
        "booking_reference": booking_reference,
        # Sixt double-spaces some station names ("Vienna-Schwechat  Airport").
        "pickup_place": re.sub(r"\s{2,}", " ", pickup_place).strip(),
        "pickup_datetime": _iso_local(pickup[0], pickup_time),
        "dropoff_place": re.sub(r"\s{2,}", " ", dropoff_place).strip(),
        "dropoff_datetime": _iso_local(dropoff[0], dropoff_time),
        "vehicle": vehicle,
    }


# ---------------------------------------------------------------------------
# Europcar
# ---------------------------------------------------------------------------


def _extract_europcar(lines: list[str]) -> dict | None:
    pickup_at = _find_index(lines, r"^Pick-?up$")
    dropoff_at = _find_index(lines, r"^Return$", start=max(pickup_at, 0))
    if pickup_at < 0 or dropoff_at < 0:
        return None

    # Place then date, each on its own line, directly under the label.
    pickup_place = lines[pickup_at + 1] if pickup_at + 1 < len(lines) else ""
    dropoff_place = lines[dropoff_at + 1] if dropoff_at + 1 < len(lines) else ""
    pickup_line = lines[pickup_at + 2] if pickup_at + 2 < len(lines) else ""
    dropoff_line = lines[dropoff_at + 2] if dropoff_at + 2 < len(lines) else ""

    month_first = _numeric_dates_month_first([pickup_line, dropoff_line])
    pickup_date = _parse_numeric_date(pickup_line, month_first)
    dropoff_date = _parse_numeric_date(dropoff_line, month_first)
    if not pickup_date or not dropoff_date:
        return None
    pickup_time = _parse_time(pickup_line)
    dropoff_time = _parse_time(dropoff_line)
    if not pickup_time or not dropoff_time:
        return None

    ref_at = _find_index(lines, r"booking\s+or\s+reservation\s+number\s+is")
    booking_reference = ""
    if ref_at >= 0:
        for line in lines[ref_at : ref_at + 3]:
            if m := re.search(r"\b(\d{6,15})\b", line):
                booking_reference = m.group(1)
                break

    driver_at = _find_index(lines, r"^Drivers?:$")
    driver = lines[driver_at + 1] if 0 <= driver_at < len(lines) - 1 else ""

    vehicle_at = _find_index(lines, r"\bor similar\b")
    vehicle = lines[vehicle_at] if vehicle_at >= 0 else ""

    return {
        "booking_reference": booking_reference,
        "pickup_place": pickup_place,
        "pickup_datetime": _iso_local(pickup_date, pickup_time),
        "dropoff_place": dropoff_place,
        "dropoff_datetime": _iso_local(dropoff_date, dropoff_time),
        "vehicle": vehicle,
        "driver_name": driver,
    }


_EXTRACTORS = {
    "Booking.com": _extract_booking_com,
    "Hertz": _extract_hertz,
    "Sixt": _extract_sixt,
    "Europcar": _extract_europcar,
}


def extract_car_rentals(email_msg) -> list[dict]:
    """Read the car rental this email confirms, or return [].

    At most one per email: none of these templates puts two rentals in one
    confirmation, and a list is returned only so the caller has the same shape
    `extract_lodging_reservations` gives it.
    """
    vendors = [v for v in (is_car_rental_sender(s) for s in candidate_senders(email_msg)) if v]
    vendor = vendors[0] if vendors else ""
    booking_broker = any(is_booking_com_car_sender(s) for s in candidate_senders(email_msg))
    if not vendor and not booking_broker:
        return []

    subjects = candidate_subjects(email_msg)
    if booking_broker:
        if any(_BOOKING_CAR_CANCELLED_RE.search(s) for s in subjects):
            return []
        if not any(_BOOKING_CAR_CONFIRMED_RE.search(s) for s in subjects):
            return []

    if booking_broker and not vendor:
        # Booking.com's template is HTML; its plain-text part is only a link to
        # view the mail online. The other three vendors use the text part, and
        # `html_to_text` would collapse their one-field-per-line layout.
        html_body = getattr(email_msg, "html_body", "") or ""
        text = html_to_text(html_body) if html_body else (getattr(email_msg, "body", "") or "")
    else:
        text = getattr(email_msg, "body", "") or ""
    lines = _lines(text)
    if not lines:
        return []

    extractor = _EXTRACTORS["Booking.com" if booking_broker and not vendor else vendor]
    try:
        record = extractor(lines)
    except Exception as exc:  # noqa: BLE001 - a malformed mail must not fail a sync
        logger.warning("Car rental: %s extraction failed: %s", vendor or "Booking.com", exc)
        return []
    if not record:
        return []
    if not record.get("pickup_place") or not record.get("dropoff_place"):
        # Both ends are required: the service refuses a nameless place, and a
        # rental with one end guessed is worse than no rental at all.
        logger.info("Car rental: %s mail named no pickup/drop-off place", vendor or "Booking.com")
        return []

    record.setdefault("vendor", vendor)
    return [{k: v for k, v in record.items() if v}]
