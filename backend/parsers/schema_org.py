"""Airline-and-platform-independent reader for schema.org reservation markup.

Google published an email-markup spec years ago and the booking platforms
embed it next to the pretty HTML: a machine-readable block naming the property,
its address, and the dates. Reading that block is categorically different from
every other parser here — there is nothing to guess at, so this tier either
finds a typed reservation or returns nothing. (That is also why it ran ahead
of the blocked-sender skip while that list existed; migration 0042 retired the
list, since a structural reader cannot produce the junk it was guarding
against.)

Deliberately **not gated on sender**. Airbnb is the only platform this was
measured against — of a 372-email corpus it was the sole source of
``LodgingReservation`` markup, with Booking.com's two emails carrying none —
but the markup is a published standard, so keying on the senders that happen to
be known today would mean a code change for every platform that ever adopts it.
An email with no markup costs one substring check.

Two renderings exist and both are handled, because the platforms disagree:

* **JSON-LD** — ``<script type="application/ld+json">`` holding the object.
  Airbnb's rendering. Sometimes HTML-entity-escaped (``&quot;``), which is why
  a failed parse is retried through ``html.unescape`` rather than discarded.
* **Microdata** — ``itemscope`` / ``itemprop`` attributes spread over ``meta``
  and ``link`` tags. Every airline that ships flight markup uses this form, so
  a lodging platform may well too.

The one piece of judgement here is ``_wall_clock``: **a UTC offset in this
markup is discarded, and only the wall clock is kept.** Measured on real mail,
three of six Airbnb records carried an offset and all three were wrong — a flat
``+01:00`` on properties in France, Italy and Poland, all of which were on
CEST (+02:00). ``+01:00`` was UK time on the stay's date, i.e. the *recipient's*
site locale (these were ``airbnb.co.uk`` mails), not the property's zone. The
wall clock, meanwhile, was right every time: 15:00/16:00 check-ins, 10:00-12:00
check-outs. Downstream, ``StayService`` re-localises that naive local time using
the property's own coordinates, which is the correct zone by construction — so
honouring the sender's offset would take a right answer and break it.
"""

import html
import json
import logging
import re
from datetime import datetime
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

__all__ = ["extract_flight_reservations", "extract_lodging_reservations"]

# A bare date carries no time, so the booking's own convention is unknowable and
# these stand in. They mirror TripStays.svelte's DEFAULT_CHECK_IN /
# DEFAULT_CHECK_OUT so an imported stay and a hand-added one seed alike.
DEFAULT_CHECK_IN_TIME = "14:00"
DEFAULT_CHECK_OUT_TIME = "11:00"

# Void elements never nest, so they must not push onto the itemscope stack.
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

# Cheap pre-filter: skip the parse entirely unless the string appears somewhere.
_MARKER = "LodgingReservation"

_CANCELLED = re.compile(r"cancel", re.I)

# Two specs disagree about what these are called, and both are in the wild.
# Google's Gmail markup reference — the one the booking platforms were written
# against, and the one Airbnb uses — says `checkinDate` / `checkoutDate`.
# schema.org's own vocabulary says `checkinTime` / `checkoutTime`, which is what
# KDE's Itinerary reads and what Hotels.com annotates with. Reading only the
# Google pair would silently extract nothing from a correctly-marked-up booking,
# which is the worst failure mode this parser has: no error, just no stay.
_CHECK_IN_KEYS = ("checkinDate", "checkinTime")
_CHECK_OUT_KEYS = ("checkoutDate", "checkoutTime")


class _MicrodataParser(HTMLParser):
    """Collect schema.org microdata items from an HTML document.

    Nesting is tracked by **element depth** rather than by matching end tags to
    the tag that opened an itemscope. Marketing HTML wraps its markup in plain
    ``<div>``s constantly, and a naive "pop when the tag matches" scheme closes
    the item on the first inner ``</div>`` — collapsing a reservation into its
    first two fields.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._stack: list[tuple[dict, int]] = []
        self._depth = 0
        self._pending: tuple[str, int] | None = None
        self._text: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _assign(self, prop: str, value) -> None:
        if not prop or not self._stack:
            return
        # First value wins: platforms restate a property in a human-readable
        # form further down, and the machine-readable one comes first.
        self._stack[-1][0].setdefault(prop, value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, _self_closing=True)

    def handle_starttag(self, tag, attrs, _self_closing: bool = False):
        a = dict(attrs)
        void = _self_closing or tag in _VOID_TAGS
        if not void:
            self._depth += 1

        if "itemscope" in a:
            item = {"@type": (a.get("itemtype") or "").rstrip("/").rsplit("/", 1)[-1]}
            self._assign(a.get("itemprop") or "", item)
            if not self._stack:
                self.items.append(item)
            self._stack.append((item, self._depth))
        elif "itemprop" in a:
            value = a.get("content") or a.get("href")
            if value is not None:
                self._assign(a["itemprop"], value.strip())
            elif not void:
                # Value is the element's text content — capture until it closes.
                self._pending = (a["itemprop"], self._depth)
                self._text = []

    def handle_data(self, data):
        if self._pending:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self._pending and self._depth <= self._pending[1]:
            self._assign(self._pending[0], " ".join("".join(self._text).split()))
            self._pending = None
        self._depth = max(0, self._depth - 1)
        while self._stack and self._stack[-1][1] > self._depth:
            self._stack.pop()


def _walk_json(node, out: list[dict]) -> None:
    """Collect every dict in a JSON-LD document, however it is wrapped.

    Publishers ship a bare object, a list of objects, or an ``@graph`` — and a
    reservation is sometimes nested inside another object.
    """
    if isinstance(node, list):
        for item in node:
            _walk_json(item, out)
    elif isinstance(node, dict):
        out.append(node)
        for value in node.values():
            if isinstance(value, list | dict):
                _walk_json(value, out)


def _json_ld_items(html_body: str) -> list[dict]:
    items: list[dict] = []
    for match in re.finditer(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html_body, re.S | re.I
    ):
        raw = match.group(1).strip()
        parsed = None
        # Some senders escape the whole block into HTML entities, so a literal
        # parse fails on `&quot;` where an unescaped one succeeds.
        for candidate in (raw, html.unescape(raw)):
            try:
                parsed = json.loads(candidate)
                break
            except (ValueError, TypeError):
                continue
        if parsed is None:
            logger.debug("schema.org: unparseable ld+json block, skipped")
            continue
        _walk_json(parsed, items)
    return items


def _microdata_items(html_body: str) -> list[dict]:
    parser = _MicrodataParser()
    try:
        parser.feed(html_body)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed marketing HTML is routine
        logger.debug("schema.org: microdata parse aborted (%s)", exc)
    collected: list[dict] = []
    _walk_json(parser.items, collected)
    return collected


def _type_of(obj: dict) -> str:
    value = obj.get("@type") or ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).rstrip("/").rsplit("/", 1)[-1]


def _text(value) -> str:
    """Flatten a property that may be a string, a list, or a nested object."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            flattened = _text(item)
            if flattened:
                return flattened
        return ""
    if isinstance(value, dict):
        return _text(value.get("name") or "")
    return ""


def _first(obj: dict, keys: tuple[str, ...]):
    """The first of several spellings of the same property that carries a value."""
    for key in keys:
        value = obj.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _wall_clock(value, *, default_time: str) -> str | None:
    """Normalise a schema.org date-time to a naive local stamp.

    Any UTC offset or trailing ``Z`` is **dropped rather than applied** — see
    the module docstring: the offsets observed in real mail were the
    recipient's, not the property's, and were wrong every time. A date with no
    time takes ``default_time``.
    """
    text = _text(value)
    if not text:
        return None
    text = text.strip().replace(" ", "T", 1) if " " in text and "T" not in text else text.strip()
    # Strip a trailing Z or ±HH:MM offset, keeping the local wall clock.
    text = re.sub(r"(?:Z|[+-]\d{2}:?\d{2})$", "", text)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T{default_time}"
    match = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", text)
    if not match:
        logger.debug("schema.org: unrecognised datetime %r", text)
        return None
    return f"{match.group(1)}T{match.group(2)}:{match.group(3)}"


def _reservation_to_stay(obj: dict) -> dict | None:
    status = _text(obj.get("reservationStatus"))
    if status and _CANCELLED.search(status):
        # A cancellation restates the whole booking; importing it would create
        # the very row it is announcing the end of.
        logger.info("schema.org: skipping cancelled lodging reservation")
        return None

    target = obj.get("reservationFor")
    target = target if isinstance(target, dict) else {}
    address = target.get("address")
    address = address if isinstance(address, dict) else {}

    check_in = _wall_clock(_first(obj, _CHECK_IN_KEYS), default_time=DEFAULT_CHECK_IN_TIME)
    check_out = _wall_clock(_first(obj, _CHECK_OUT_KEYS), default_time=DEFAULT_CHECK_OUT_TIME)
    if not check_in or not check_out:
        return None
    try:
        if datetime.fromisoformat(check_out) <= datetime.fromisoformat(check_in):
            logger.info("schema.org: lodging check-out not after check-in, skipped")
            return None
    except ValueError:
        return None

    locality = _text(address.get("addressLocality"))
    street = _text(address.get("streetAddress"))
    # The property name is missing on real records (one of six in the measured
    # corpus had neither a name nor a reservation number). `name` is NOT NULL on
    # trip_stays, and a row reading "Moneglia" is far better than a dropped
    # booking, so the locality stands in before the street does.
    name = _text(target.get("name")) or locality or street
    if not name:
        return None

    country = _text(address.get("addressCountry"))
    # Publishers send either the ISO code or the country's name; only the former
    # is a country code, and guessing at the latter is what migration 0025
    # exists to prevent.
    country_code = country.upper() if re.fullmatch(r"[A-Za-z]{2}", country) else None

    return {
        "name": name,
        "address": street or None,
        "city": locality or None,
        "country_code": country_code,
        "check_in_datetime": check_in,
        "check_out_datetime": check_out,
        "booking_reference": _text(obj.get("reservationNumber")) or None,
        "contact": _text(target.get("telephone")) or None,
        "price": _lodging_price(obj),
    }


def _lodging_price(obj: dict) -> tuple[float, str] | None:
    """``totalPrice`` + ``priceCurrency``, when the publisher states both.

    None of the measured Airbnb records carries a price, so this reads only the
    plain shape the spec gives (a number, or a PriceSpecification with ``price``)
    and an ISO currency code; anything else is no price rather than a guess.
    """
    from ..expenses.domain import SUPPORTED_CURRENCIES

    total = obj.get("totalPrice")
    currency = _text(obj.get("priceCurrency"))
    if isinstance(total, dict):
        currency = currency or _text(total.get("priceCurrency"))
        total = total.get("price")
    raw = str(total) if isinstance(total, int | float) else _text(total)
    try:
        amount = float(raw.replace(",", ""))
    except ValueError:
        return None
    code = currency.upper()
    if amount <= 0 or code not in SUPPORTED_CURRENCIES:
        return None
    return round(amount, 2), code


def extract_lodging_reservations(email_msg) -> list[dict]:
    """Return every lodging booking this email declares in schema.org markup.

    Returns ``[]`` for anything without a typed ``LodgingReservation`` — there
    is no fallback and no proximity guessing, by design.
    """
    body = getattr(email_msg, "html_body", None) or getattr(email_msg, "body", "") or ""
    if _MARKER not in body:
        return []

    objects = _json_ld_items(body) + _microdata_items(body)

    stays: list[dict] = []
    seen: set[tuple] = set()
    for obj in objects:
        if _type_of(obj) != _MARKER:
            continue
        stay = _reservation_to_stay(obj)
        if stay is None:
            continue
        # One booking is restated per guest in some renderings, exactly as the
        # flight markup restates a leg per passenger.
        key = (
            stay["booking_reference"],
            stay["name"],
            stay["check_in_datetime"],
            stay["check_out_datetime"],
        )
        if key in seen:
            continue
        seen.add(key)
        stays.append(stay)
    return stays


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------
#
# The same markup, for flights. Airlines ship it so Gmail can show a flight
# card: Ryanair, Lufthansa, TAP and Austrian all do, as microdata, one
# FlightReservation per leg (and per passenger). Every one of those already has
# its own rule here, so this tier exists for the airline that does not: it runs
# only when the rules and the e-ticket reader found nothing, ahead of the LLM,
# because a typed record cannot invert a route or invent a flight number.
#
# Times are the one place this differs from the lodging reader: an offset is
# **honoured**, not dropped. Airbnb's offsets were the recipient's locale and
# wrong; the airlines' were right in every mail measured (Lufthansa's
# "20240329T054500Z" is the 06:45 Arlanda departure in true UTC, Austrian's
# "+01:00" is Frankfurt in January). A time without an offset is local to its
# airport, as everywhere else. Either way the leg leaves here in UTC, flagged so
# apply_airport_timezones does not localise it a second time.

_FLIGHT_MARKER = "FlightReservation"
_IATA = re.compile(r"[A-Z]{3}")
_AIRLINE_CODE = re.compile(r"[A-Z0-9]{2}")
# ISO 8601 basic format, as Lufthansa writes it: 20240329T054500Z
_BASIC_STAMP = re.compile(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z|[+-]\d{2}:?\d{2})?")


def _airport_code(airport) -> str:
    """The airport's IATA code, only when the markup states one.

    Names are not resolved: Ryanair marks a Bergamo arrival as just "Milan",
    which resolves to Malpensa. A leg missing from the trip is visible; one at
    the wrong airport is not.
    """
    if not isinstance(airport, dict):
        return ""
    for value in (airport.get("iataCode"), airport.get("name")):
        code = _text(value).upper()
        if _IATA.fullmatch(code):
            return code
    return ""


def _flight_time(value, airport: str) -> datetime | None:
    """A departure or arrival time as aware UTC, or None without a clock time."""
    from ..airports.timezone import localize_to_utc

    text = _text(value)
    basic = _BASIC_STAMP.fullmatch(text)
    if basic:
        y, mo, d, h, mi, sec, off = basic.groups()
        text = f"{y}-{mo}-{d}T{h}:{mi}:{sec or '00'}{off or ''}"
    if ":" not in text:
        # A bare date ("2019-01-24") or a label ("23FEB") says nothing about when.
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        logger.debug("schema.org: unrecognised flight time %r", text)
        return None
    return localize_to_utc(stamp, airport)


def _reservation_to_flight(obj: dict) -> dict | None:
    from ..utils.dates import FLIGHT_NUMBER_RE

    status = _text(obj.get("reservationStatus"))
    if status and _CANCELLED.search(status):
        logger.info("schema.org: skipping cancelled flight reservation")
        return None

    flight = obj.get("reservationFor")
    flight = flight if isinstance(flight, dict) else {}
    airline = flight.get("airline")
    airline = airline if isinstance(airline, dict) else {}
    airline_code = _text(airline.get("iataCode")).upper()
    if not _AIRLINE_CODE.fullmatch(airline_code):
        airline_code = ""

    number = re.sub(r"[\s\xa0-]", "", _text(flight.get("flightNumber"))).upper()
    if number.isdigit() and airline_code:
        number = airline_code + number
    if not FLIGHT_NUMBER_RE.match(number):
        return None

    dep = _airport_code(flight.get("departureAirport"))
    arr = _airport_code(flight.get("arrivalAirport"))
    if not dep or not arr or dep == arr:
        return None
    dep_dt = _flight_time(flight.get("departureTime"), dep)
    if dep_dt is None:
        return None

    return {
        "flight_number": number,
        "departure_airport": dep,
        "arrival_airport": arr,
        "departure_datetime": dep_dt,
        "arrival_datetime": _flight_time(flight.get("arrivalTime"), arr),
        "booking_reference": _text(obj.get("reservationNumber")),
        "passenger_name": _text(obj.get("underName")),
        "seat": _text(obj.get("airplaneSeat")),
        "cabin_class": _text(obj.get("airplaneSeatClass")),
        "airline_name": _text(airline.get("name")) or airline_code,
        "airline_code": airline_code or number[:2],
        "departure_terminal": _text(flight.get("departureTerminal")),
        "arrival_terminal": _text(flight.get("arrivalTerminal")),
        "departure_gate": _text(flight.get("departureGate")),
        "arrival_gate": _text(flight.get("arrivalGate")),
        "_times_already_utc": True,
    }


def extract_flight_reservations(email_msg) -> list[dict]:
    """Return every flight leg this email declares in schema.org markup.

    One dict per leg in the rule parsers' shape, times in UTC. A leg
    restated per passenger is returned once. ``[]`` without typed markup.
    """
    body = getattr(email_msg, "html_body", None) or getattr(email_msg, "body", "") or ""
    if _FLIGHT_MARKER not in body:
        return []

    flights: list[dict] = []
    seen: set[tuple] = set()
    for obj in _json_ld_items(body) + _microdata_items(body):
        if _type_of(obj) != _FLIGHT_MARKER:
            continue
        flight = _reservation_to_flight(obj)
        if flight is None:
            continue
        key = (flight["flight_number"], flight["departure_airport"], flight["departure_datetime"])
        if key in seen:
            continue
        seen.add(key)
        flights.append(flight)
    return flights
