"""Trip.com hotel booking confirmations — the template, read structurally.

Trip.com, like Booking.com, ships **no** schema.org markup, so ``schema_org.py``
cannot see its hotel confirmations. This reader follows ``booking_com.py``:
gated on the sender, keyed on Trip.com's own labels, and returning nothing for
anything it does not recognise.

The HTML confirmation (what ``html_to_text`` gives) prints each fact as a label
on its own line followed by its value:

    Booking details
    Check-in
    Mar 24, 2027
    After 14:00
    Hotel's local time
    Check-out
    Mar 27, 2027
    Before 12:00
    ...
    Address
    No. 7 Qianjing Hutong, Xicheng District, Beijing, China
    北京西城区前井胡同7号

Times are the "After" of check-in and the "Before" of check-out, returned as
*naive local* ISO strings — the same contract ``schema_org`` has, so
``StayService`` re-localises them from the property's own coordinates.

Four decisions are deliberate:

- The **booking reference is Trip.com's "Booking no."**, not the "Hotel
  confirmation number" printed beside it. The platform number is what every
  later Trip.com mail about the booking repeats, which is what the importer's
  idempotency keys on.
- The **address is the first line under its label only.** China properties
  print the local-script address on the line after, and folding it in would
  hand the geocoder a query it cannot match. That line is returned apart, as
  ``local_address``: OSM names Chinese streets in Chinese, so its street is
  what finds the hotel when the English rendering does not
  (``sync/stay_geocode.py``).
- The **guest count is left out.** The template lists only the guest names
  entered at booking (often just the lead guest), and the room's *capacity*
  ("up to 2 guests") is not how many people are coming. A wrong count is worse
  than none.
- The **country** is printed as a name inside the address, never as a code, and
  is left to the importer's geocode for the same reason ``booking_com`` does.
- The **price is the "Total"** at the foot of "Price details", which is what
  was charged: the room rate above it is before Trip.com's discounts ("China
  travel deal -SEK 687.00", ...), and the cancellation fees and per-person
  breakfast prices elsewhere in the mail are not the booking's cost.

Trip.com also sells flights and trains from other ``trip.com`` mailboxes; the
hotel template is recognised by its own subject and "Booking details" block, so
those mails yield nothing here.
"""

import logging
import re
from datetime import date as date_type

from .engine import parse_flight_date
from .schema_org import DEFAULT_CHECK_IN_TIME, DEFAULT_CHECK_OUT_TIME
from .shared import html_to_text, parse_money

logger = logging.getLogger(__name__)

__all__ = ["extract_trip_com_stays", "is_trip_com_sender"]

_SENDER_RE = re.compile(r"[@.]trip\.com\b", re.IGNORECASE)
_CONFIRMED_RE = re.compile(r"\bhas been confirmed\b|\[Booking confirmation\]", re.IGNORECASE)
_CANCELLED_RE = re.compile(r"cancel", re.IGNORECASE)

_SUBJECT_NAME_RE = re.compile(r"Your booking at (.+?) has been confirmed", re.IGNORECASE)
_STAY_AT_RE = re.compile(r"Your stay at (.+?) \(check-in:", re.IGNORECASE)
_CITY_RE = re.compile(r"for your stay in (.+?) is confirmed", re.IGNORECASE)
_DATE_RE = re.compile(r"[^\W\d_]{3,9}\.?\s+\d{1,2},?\s+\d{4}")
_CLOCK_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_PHONE_RE = re.compile(r"^Call\s*(\+?[\d\s().-]{6,})$")
_ROOMS_NIGHTS_RE = re.compile(r"^\d+\s+Rooms?\s+\d+\s+nights?$", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"^\d{8,}$")
_LOCAL_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
# Trip.com sprinkles zero-width non-joiners through the header's booking number
# ("1‌688‌902…") so mail clients do not autolink it.
_ZERO_WIDTH_RE = re.compile(r"[​-‍﻿]")


def is_trip_com_sender(sender: str) -> bool:
    return bool(_SENDER_RE.search(sender or ""))


def _lines(text: str) -> list[str]:
    cleaned = _ZERO_WIDTH_RE.sub("", text or "")
    return [line.strip() for line in cleaned.split("\n") if line.strip()]


def _after(lines: list[str], label: str, count: int) -> list[str]:
    """The ``count`` lines following the first line that is exactly ``label``."""
    for i, line in enumerate(lines):
        if line == label:
            return lines[i + 1 : i + 1 + count]
    return []


def _when(lines: list[str], label: str, default_time: str) -> str | None:
    """Read "Check-in / Mar 24, 2027 / After 14:00" as "2027-03-24T14:00"."""
    value = " ".join(_after(lines, label, 2))
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


def _property_name(subject: str, text: str) -> str:
    for rx, source in ((_SUBJECT_NAME_RE, subject), (_STAY_AT_RE, text)):
        m = rx.search(source or "")
        if m:
            return m.group(1).strip()
    return ""


def _booking_reference(lines: list[str]) -> str | None:
    for value in _after(lines, "Booking no.", 1) + _after(lines, "Booking No.", 1):
        if _REFERENCE_RE.match(value):
            return value
    return None


def _room_type(lines: list[str]) -> str | None:
    """The line above "1 Room 3 nights" in the room block, which sits directly
    over "Guest names". The same count line also follows "Your booking" in the
    summary, where the line above it is that label, not a room."""
    for i, line in enumerate(lines):
        if line == "Guest names" and i >= 2 and _ROOMS_NIGHTS_RE.match(lines[i - 1]):
            return lines[i - 2]
    return None


def _price(lines: list[str]) -> tuple[float, str] | None:
    """The "Total" of the price block: "Total / Prepay Online / SEK 2,003.00"."""
    start = next((i for i, ln in enumerate(lines) if ln == "Price details"), -1)
    if start < 0:
        return None
    for value in _after(lines[start:], "Total", 2):
        money = parse_money(value)
        if money:
            return money
    return None


def _contact(lines: list[str]) -> str | None:
    for line in lines:
        m = _PHONE_RE.match(line)
        if m:
            return m.group(1).strip()
    return None


def extract_trip_com_stays(email_msg) -> list[dict]:
    """Read the stay a Trip.com hotel confirmation declares, or return ``[]``.

    The returned dict has the shape ``schema_org.extract_lodging_reservations``
    gives, plus ``room_type`` and ``guests``, so the importer treats both alike.
    """
    if not is_trip_com_sender(getattr(email_msg, "sender", "") or ""):
        return []
    subject = getattr(email_msg, "subject", "") or ""
    if _CANCELLED_RE.search(subject):
        # The body says "Free cancellation" on every confirmation, so only the
        # subject can say the booking itself is cancelled.
        return []
    if not _CONFIRMED_RE.search(subject):
        return []

    html_body = getattr(email_msg, "html_body", None)
    text = html_to_text(html_body) if html_body else (getattr(email_msg, "body", "") or "")
    lines = _lines(text)
    details = next((i for i, ln in enumerate(lines) if ln == "Booking details"), -1)
    if details < 0:
        logger.info("Trip.com: confirmation without a Booking details block, skipped")
        return []
    fields = lines[details:]

    check_in = _when(fields, "Check-in", DEFAULT_CHECK_IN_TIME)
    check_out = _when(fields, "Check-out", DEFAULT_CHECK_OUT_TIME)
    name = _property_name(subject, _ZERO_WIDTH_RE.sub("", text))
    if not (check_in and check_out and name):
        logger.info("Trip.com: confirmation without dates or property name, skipped")
        return []
    if check_out <= check_in:
        logger.info("Trip.com: check-out not after check-in, skipped")
        return []

    city = _CITY_RE.search(text)
    address = _after(fields, "Address", 2)
    # The line under the address, when it is the local-script one (China).
    local = address[1] if len(address) > 1 and _LOCAL_SCRIPT_RE.search(address[1]) else None

    stay = {
        "name": name,
        "address": address[0] if address else None,
        "local_address": local,
        "city": city.group(1).strip() if city else None,
        "country_code": None,
        "check_in_datetime": check_in,
        "check_out_datetime": check_out,
        "booking_reference": _booking_reference(lines),
        "contact": _contact(lines),
        "room_type": _room_type(lines),
        "guests": None,
        "price": _price(lines),
    }
    return [stay]
