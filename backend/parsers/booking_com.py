"""Booking.com booking confirmations — the template, read structurally.

Booking.com ships **no** schema.org markup (both of its mails in the measured
corpus and the 2026 confirmation this was written against carry none), so
``schema_org.py`` cannot see it. This reader fills that gap the way
``car_rental.py`` does for the rental vendors: gated on the sender, keyed on
Booking.com's own labels, and returning nothing for anything it does not
recognise. There is no proximity guessing — a missing label is a missing
booking, not an invitation to look nearby.

The confirmation lays every fact out as a label followed by its value, and the
two renderings put them in different places, so the extractor tolerates both:

  HTML (what ``html_to_text`` gives, and what the sync passes as ``body``)
      Check-in
      Tuesday, 22 December 2026
      (14:00 - 00:00)
  text/plain
      Check-in Tuesday, 22 December 2026 (14:00 - 00:00)

Times are the start of the check-in window and the end of the check-out one
("until 12:00"), returned as *naive local* ISO strings — the same contract
``schema_org`` has, so ``StayService`` re-localises them from the property's own
coordinates.

Three things are deliberately left out. The **country** is printed as a name
("Portugal"), never a code, and guessing a code from a name is what migration
0025 exists to prevent — the importer's geocode supplies it instead. The
**"Special Request"** mails a property sends through ``property.booking.com``
restate the dates but carry no address and no times; they are not confirmations
and are skipped. And only the **English** template is read: it is the only one
measured, and a localised template would need its own labels rather than a
guess at them.
"""

import logging
import re
from datetime import date as date_type

from .engine import parse_flight_date
from .schema_org import DEFAULT_CHECK_IN_TIME, DEFAULT_CHECK_OUT_TIME
from .shared import html_to_text

logger = logging.getLogger(__name__)

__all__ = ["extract_booking_com_stays", "is_booking_com_sender"]

_SENDER_RE = re.compile(r"[@.]booking\.com\b", re.IGNORECASE)
_CONFIRMED_RE = re.compile(r"\bbooking (?:in .+? )?is confirmed\b", re.IGNORECASE)
_CANCELLED_RE = re.compile(r"cancel", re.IGNORECASE)

_SUBJECT_NAME_RE = re.compile(r"confirmed at (.+?)\s*$", re.IGNORECASE)
_EXPECTING_RE = re.compile(r"^(?:\[[^\]]*\]\s*)?(.*?)\s*is expecting you\b", re.IGNORECASE)
_CITY_RE = re.compile(r"Your booking in (.+?) is confirmed", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"\bConfirmation(?: number)?:\s*(\d{6,})")
_DATE_RE = re.compile(r"\d{1,2}\s+[^\W\d_]+\.?\s+\d{4}")
_CLOCK_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{6,}$")
_NIGHTS_RE = re.compile(r"\d+\s+nights?\b,?\s*", re.IGNORECASE)

# Labels that start a new field. A value window stops at the next of these, so
# a field printed without its value never reads its neighbour's.
_LABELS = (
    "Check-in",
    "Check-out",
    "Your reservation",
    "You booked for",
    "Location",
    "Phone",
    "Contact",
    "Cancellation policy",
)
_LABEL_RE = re.compile(r"^(?:" + "|".join(re.escape(lb) for lb in _LABELS) + r")\b")


def is_booking_com_sender(sender: str) -> bool:
    return bool(_SENDER_RE.search(sender or ""))


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").split("\n") if line.strip()]


def _field(lines: list[str], label: str, extra: int = 2) -> str:
    """The value printed under ``label``: the rest of the label's own line (the
    plain-text rendering) plus up to ``extra`` following lines (the HTML one),
    stopping at the next label. Empty when the label is absent.

    The label must open its line — "Guests are required to show … upon
    check-in" in the small print is not the Check-in field.
    """
    rx = re.compile(r"^" + re.escape(label) + r"\b\s*")
    for i, line in enumerate(lines):
        m = rx.match(line)
        if not m:
            continue
        parts = [line[m.end() :]]
        for nxt in lines[i + 1 : i + 1 + extra]:
            if _LABEL_RE.match(nxt):
                break
            parts.append(nxt)
        return " ".join(p for p in parts if p).strip()
    return ""


def _when(value: str, default_time: str) -> str | None:
    """Read "Tuesday, 22 December 2026 (14:00 - 00:00)" as "2026-12-22T14:00".

    The first clock after the date is the one that matters on both ends: the
    start of the check-in window, the "until" of the check-out.
    """
    m = _DATE_RE.search(value)
    if not m:
        return None
    day: date_type | None = parse_flight_date(m.group(0))
    if day is None:
        return None
    clock = _CLOCK_RE.search(value, m.end())
    hhmm = default_time
    if clock and int(clock.group(1)) < 24 and int(clock.group(2)) < 60:
        hhmm = f"{int(clock.group(1)):02d}:{clock.group(2)}"
    return f"{day.isoformat()}T{hhmm}"


def _property_name(subject: str, lines: list[str]) -> str:
    m = _SUBJECT_NAME_RE.search(subject or "")
    if m:
        return m.group(1).strip()
    # "B&B HOTEL Lisboa Aeroporto is expecting you on Tue 22 Dec" — on one line
    # in the text part, split across two in the HTML.
    for i, line in enumerate(lines):
        m = _EXPECTING_RE.match(line)
        if not m:
            continue
        if m.group(1):
            return m.group(1)
        if i > 0:
            return lines[i - 1]
    return ""


def _guest_count(value: str) -> int | None:
    """Total the party: "2 adults, 1 child" is 3."""
    counts = [int(n) for n in re.findall(r"\d+", value)]
    return sum(counts) or None


def _contact(value: str) -> str | None:
    value = value.split(" Contact", 1)[0].strip()
    return value if _PHONE_RE.match(value) else None


def extract_booking_com_stays(email_msg) -> list[dict]:
    """Read the stay a Booking.com confirmation declares, or return ``[]``.

    The returned dict has the shape ``schema_org.extract_lodging_reservations``
    gives, plus ``room_type`` and ``guests``, so the importer treats both alike.
    """
    if not is_booking_com_sender(getattr(email_msg, "sender", "") or ""):
        return []
    subject = getattr(email_msg, "subject", "") or ""
    if _CANCELLED_RE.search(subject):
        # A cancellation restates the booking; importing it would create the
        # very row it announces the end of.
        return []

    html_body = getattr(email_msg, "html_body", None)
    text = html_to_text(html_body) if html_body else (getattr(email_msg, "body", "") or "")
    if not (_CONFIRMED_RE.search(subject) or _CONFIRMED_RE.search(text)):
        return []
    lines = _lines(text)
    # Every field is read from the block under "Reservation details". Above it
    # sits a payment banner, "Your reservation is paid with Booking.com", which
    # opens with the same words as the room field's label.
    details = next((i for i, ln in enumerate(lines) if ln.startswith("Reservation details")), -1)
    if details < 0:
        logger.info("Booking.com: confirmation without a Reservation details block, skipped")
        return []
    fields = lines[details:]

    check_in = _when(_field(fields, "Check-in"), DEFAULT_CHECK_IN_TIME)
    check_out = _when(_field(fields, "Check-out"), DEFAULT_CHECK_OUT_TIME)
    name = _property_name(subject, lines)
    if not (check_in and check_out and name):
        logger.info("Booking.com: confirmation without dates or property name, skipped")
        return []
    if check_out <= check_in:
        logger.info("Booking.com: check-out not after check-in, skipped")
        return []

    reference = _REFERENCE_RE.search(text)
    city = _CITY_RE.search(text)
    address = _field(fields, "Location", extra=1)
    room = _NIGHTS_RE.sub("", _field(fields, "Your reservation")).strip(" ,")

    stay = {
        "name": name,
        "address": address or None,
        "city": city.group(1).strip() if city else None,
        "country_code": None,
        "check_in_datetime": check_in,
        "check_out_datetime": check_out,
        "booking_reference": reference.group(1) if reference else None,
        "contact": _contact(_field(fields, "Phone", extra=1)),
        "room_type": room or None,
        "guests": _guest_count(_field(fields, "You booked for", extra=1)),
    }
    return [stay]
