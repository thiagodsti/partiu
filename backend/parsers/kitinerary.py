"""KDE Itinerary's extractor as an extraction tier.

KItinerary (https://invent.kde.org/pim/kitinerary) is KDE's open-source
itinerary extractor: ~370 per-provider extractors plus generic readers for
schema.org markup, IATA boarding-pass barcodes, Apple Wallet passes and PDFs.
It covers carriers Partiu has no rule for (easyJet, KLM, Swiss, Eurowings, Aer
Lingus, IndiGo, ...) and is the same structural kind of reader as ours: a
per-template extractor that finds what it knows or returns nothing — not the
proximity guessing this codebase removed.

**Where it sits.** After the airline rule, the GDS merge and the schema.org
reader, and only when all three found nothing; before the LLM. On the 372-mail
corpus it found 113 flights to the rules' 192, agreed on 87 and added 3 (all
without times, which the plausibility gate refuses) — the corpus is one
traveller's mail, already covered by rules, so that measures overlap rather
than what it adds for someone else's airlines.

**How it runs.** As a subprocess on the email's raw bytes, ``kitinerary-
extractor`` reading stdin and printing JSON-LD. The Docker image ships KDE's
static x86_64 build in ``/opt/kitinerary`` (~35 MB; the distro package pulled
in ~600 MB of Qt). ``settings.KITINERARY_EXTRACTOR`` points at it; empty, or a
path with no executable, switches the tier off and every call returns ``[]``.

**What is trusted.** Its JSON-LD goes through ``schema_org.flights_from_items``
— the conversion the email markup uses — so the same refusals apply: no IATA
code, no clock time, a cancelled reservation or a malformed number means no
leg. Times carry their offset, so legs come back in UTC and flagged
``_times_already_utc``; ``validate_flights`` still judges them like any other.

One difference from the markup reader needs a guard of its own: KItinerary
**fills a missing IATA code from the airport's name** when the name matches a
single airport, and the CLI has no switch for it. Partiu takes an airport only
when the email states it (a name like Ryanair's "Milan" resolves to the wrong
airport), so a leg is kept only when the email **pins down** both airports:
prints the code, or a word or phrase that names that airport alone
("Malpensa", "Lisbon" — not "Milan", which is LIN, MXP and BGY). Without airport
data nothing can be confirmed and the leg is refused. That is stricter than the
check the LLM's answers pass (``parsers/airport_grounding``), on purpose: a
city name tells the model nothing it can be held to, but here the code was
chosen for us and has to be earned.

Never fatal: a missing binary, a timeout, a crash or unparseable output is
logged and yields ``[]``, so the LLM still gets its turn.
"""

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from email.message import EmailMessage as MimeMessage
from email.utils import format_datetime

from ..config import settings
from .airport_grounding import airport_stated_in_text
from .schema_org import flights_from_items

logger = logging.getLogger(__name__)

# Generous: the extractor renders PDFs, and the corpus's slowest mail took a
# few seconds natively. A hang must not stall the sync.
_TIMEOUT_SECONDS = 30


def extractor_path() -> str | None:
    """The configured kitinerary-extractor, or None when the tier is off."""
    path = (settings.KITINERARY_EXTRACTOR or "").strip()
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return None


def available() -> bool:
    return extractor_path() is not None


def _raw_bytes(email_msg) -> bytes:
    """The email as MIME bytes: the original when the fetch kept it, otherwise
    rebuilt from the parts Partiu holds (body, HTML, PDF attachments)."""
    raw = getattr(email_msg, "raw_eml", None)
    if raw:
        return raw
    msg = MimeMessage()
    for header, value in (
        ("From", getattr(email_msg, "sender", "")),
        ("Subject", getattr(email_msg, "subject", "")),
        ("Message-ID", getattr(email_msg, "message_id", "")),
    ):
        if value:
            msg[header] = " ".join(str(value).split())
    date = getattr(email_msg, "date", None)
    if date is not None:
        try:
            msg["Date"] = format_datetime(date)
        except (TypeError, ValueError):
            pass
    msg.set_content(getattr(email_msg, "body", "") or "")
    html = getattr(email_msg, "html_body", None)
    if html:
        msg.add_alternative(html, subtype="html")
    for i, pdf in enumerate(getattr(email_msg, "pdf_attachments", None) or []):
        if isinstance(pdf, bytes):
            msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"{i}.pdf")
    return bytes(msg)


def _flatten_times(node):
    """KItinerary writes times as {"@type": "QDateTime", "@value": "...+01:00",
    "timezone": "..."}; the schema.org conversion reads a plain ISO string."""
    if isinstance(node, dict):
        if node.get("@type") == "QDateTime" and isinstance(node.get("@value"), str):
            return node["@value"]
        return {k: _flatten_times(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_flatten_times(v) for v in node]
    return node


def run_extractor(email_msg) -> list[dict]:
    """Raw JSON-LD objects for the email, or [] when the tier is off or fails."""
    path = extractor_path()
    if path is None:
        return []
    args = [path]
    date = getattr(email_msg, "date", None)
    if date is not None:
        # The year of a year-less date ("12NOV") is resolved against this.
        args += ["--context-date", date.isoformat()]
    try:
        result = subprocess.run(
            args,
            input=_raw_bytes(email_msg),
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
            # Qt warns and switches locale without a UTF-8 one.
            env={**os.environ, "LANG": "C.UTF-8"},
        )
    except subprocess.TimeoutExpired:
        logger.warning("kitinerary: timed out on %r", getattr(email_msg, "subject", "")[:60])
        return []
    except OSError as e:
        logger.warning("kitinerary: could not run %s: %s", path, e)
        return []
    if result.returncode != 0:
        logger.warning(
            "kitinerary: exit %d on %r", result.returncode, getattr(email_msg, "subject", "")[:60]
        )
        return []
    try:
        data = json.loads(result.stdout or b"[]")
    except ValueError:
        logger.warning("kitinerary: unparseable output")
        return []
    items = data if isinstance(data, list) else [data]
    return [_flatten_times(item) for item in items if isinstance(item, dict)]


def kitinerary_items(email_msg) -> list[dict]:
    """``run_extractor``'s result, run at most once per email.

    The flight tier, the stays and rentals imports and the ground-leg and
    planner imports all read the same output; caching it on the message keeps
    that to one subprocess per email.
    """
    cached = getattr(email_msg, "_kitinerary_items", None)
    if cached is None:
        cached = run_extractor(email_msg)
        try:
            email_msg._kitinerary_items = cached
        except AttributeError:  # a message type that refuses new attributes
            pass
    return cached


def _email_text(email_msg) -> str:
    """Everything the email says, for checking a place is named in it.

    The subject, the body (which, as fetched, already folds in the text of PDF
    attachments) and the HTML — a ticket whose stations appear only in its
    HTML or its attached PDF must not be refused for it.
    """
    parts = [getattr(email_msg, "subject", "") or "", getattr(email_msg, "body", "") or ""]
    html = getattr(email_msg, "html_body", None)
    if html:
        from .email_connector import html_to_text

        parts.append(html_to_text(html))
    for pdf in getattr(email_msg, "pdf_attachments", None) or []:
        if isinstance(pdf, bytes):
            from .email_connector import _extract_text_from_pdf

            parts.append(_extract_text_from_pdf(pdf) or "")
    return "\n".join(parts)


def _named_in_email(flight: dict, email_msg) -> bool:
    """Both airports are named in the email (see the module docstring)."""
    text = _email_text(email_msg)
    for field in ("departure_airport", "arrival_airport"):
        if not airport_stated_in_text(flight[field], text):
            logger.info(
                "kitinerary: dropping %s, %s %s is not named in the email",
                flight["flight_number"],
                field.split("_")[0],
                flight[field],
            )
            return False
    return True


def extract_kitinerary_flights(email_msg) -> list[dict]:
    """Flight legs KItinerary finds in the email, in the rule parsers' shape."""
    flights = [
        f for f in flights_from_items(kitinerary_items(email_msg)) if _named_in_email(f, email_msg)
    ]
    if flights:
        logger.info(
            "kitinerary: %d flight(s) from %r",
            len(flights),
            getattr(email_msg, "subject", "")[:60],
        )
    return flights


# ---------------------------------------------------------------------------
# Everything else KItinerary reads: ground legs, stays, rentals, bookings
# ---------------------------------------------------------------------------
#
# Each converter returns the shape its importer already takes, so the trip
# matching, idempotency and "imports create, never delete" rules stay where
# they live. Every one refuses a cancelled reservation and a record without a
# clock time, as the flight conversion does.

_CANCELLED_STATUS = re.compile(r"cancel", re.IGNORECASE)

# schema.org reservation type -> (trip type, Partiu segment type, the trip's
# departure/arrival place keys, the service-number key)
_GROUND_TYPES = {
    "TrainReservation": ("TrainTrip", "train", "departureStation", "arrivalStation", "trainNumber"),
    "BusReservation": ("BusTrip", "bus", "departureBusStop", "arrivalBusStop", "busNumber"),
    "BoatReservation": (
        "BoatTrip",
        "ferry",
        "departureBoatTerminal",
        "arrivalBoatTerminal",
        None,
    ),
}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _type(obj) -> str:
    t = obj.get("@type") if isinstance(obj, dict) else None
    return t.rsplit("/", 1)[-1] if isinstance(t, str) else ""


def _str(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or ""
    return " ".join(str(value).split()) if value not in (None, "") else ""


def _cancelled(obj: dict) -> bool:
    return bool(_CANCELLED_STATUS.search(_str(obj.get("reservationStatus"))))


def _local_time(value) -> str | None:
    """A time as naive local wall clock ("2026-03-10T07:05"), or None without a
    clock time.

    KItinerary writes either a plain local string (trains, buses) or one with
    the local offset (events, rentals); the wall clock is the same either way,
    and the importers localise it from the place's own coordinates. A bare date
    is not a time: "2026-03-10" would put a 06:00 train at midnight.
    """
    text = _str(value)
    if ":" not in text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp.replace(tzinfo=None).isoformat(timespec="minutes")


def _place(obj) -> dict:
    """Name, coordinates and ISO country of a station, stop or venue."""
    obj = _dict(obj)
    geo = _dict(obj.get("geo"))
    address = _dict(obj.get("address"))
    country = _str(address.get("addressCountry"))
    try:
        lat = float(geo["latitude"]) if "latitude" in geo else None
        lon = float(geo["longitude"]) if "longitude" in geo else None
    except (TypeError, ValueError):
        lat = lon = None
    return {
        "name": _str(obj.get("name")),
        "lat": lat,
        "lon": lon,
        # Only an ISO code is a country code; a country's name is not guessed
        # into one (the rule migration 0025 exists for).
        "country_code": country.upper() if re.fullmatch(r"[A-Za-z]{2}", country) else None,
        "address": _str(address.get("streetAddress")) or None,
        "city": _str(address.get("addressLocality")) or None,
    }


def _place_named_in(name: str, text: str) -> bool:
    """The email names this station or venue.

    KItinerary may complete a name from its own station database ("MONTPELLIER
    ST-RO" can come back longer), so the whole string is not required — but at
    least one locating word of it must be in the mail, or nothing in the email
    supports the place at all.
    """
    from ..utils import fold_text
    from .shared import _significant_tokens

    folded = fold_text(text)
    words = [w for w in _significant_tokens(fold_text(name)) if len(w) >= 3]
    return bool(words) and any(re.search(rf"\b{re.escape(w)}\b", folded) for w in words)


def _seat(reservation: dict) -> str | None:
    seat = _dict(_dict(reservation.get("reservedTicket")).get("ticketedSeat"))
    if not seat:
        return None
    number, coach = _str(seat.get("seatNumber")), _str(seat.get("seatSection"))
    if coach and number:
        return f"Coach {coach}, seat {number}"
    return number or (f"Coach {coach}" if coach else None)


def ground_legs_from_items(items: list[dict], email_text: str = "") -> list[dict]:
    """Train, bus and ferry legs, in the shape ``SegmentService`` takes.

    Times are naive local wall clock; places carry KItinerary's coordinates and
    country when it has them (the importer geocodes the rest). A leg is
    refused when it is cancelled, lacks either clock time, arrives before it
    departs, or names a place the email does not.
    """
    legs: list[dict] = []
    seen: set[tuple] = set()
    for obj in items:
        spec = _GROUND_TYPES.get(_type(obj))
        if spec is None or _cancelled(obj):
            continue
        _trip_type, kind, dep_key, arr_key, number_key = spec
        trip = _dict(obj.get("reservationFor"))
        dep, arr = _place(trip.get(dep_key)), _place(trip.get(arr_key))
        dep_time, arr_time = (
            _local_time(trip.get("departureTime")),
            _local_time(trip.get("arrivalTime")),
        )
        if not (dep["name"] and arr["name"] and dep_time and arr_time):
            continue
        if email_text and not (
            _place_named_in(dep["name"], email_text) and _place_named_in(arr["name"], email_text)
        ):
            logger.info(
                "kitinerary: dropping a %s leg whose stations the email does not name", kind
            )
            continue
        number = _str(trip.get(number_key)) if number_key else ""
        if kind == "bus" and not number:
            number = _str(trip.get("busName"))
        operator = (
            _str(trip.get("provider"))
            or _str(trip.get("trainCompany"))
            or _str(trip.get("busCompany"))
        )
        key = (kind, dep["name"].lower(), dep_time, number)
        if key in seen:  # one leg restated per passenger
            continue
        seen.add(key)
        legs.append(
            {
                "type": kind,
                "operator": operator or None,
                "number": number or _str(trip.get("trainName")) or None,
                "booking_reference": _str(obj.get("reservationNumber")) or None,
                "departure": dep,
                "arrival": arr,
                "departure_datetime": dep_time,
                "arrival_datetime": arr_time,
                "seat": _seat(obj),
            }
        )
    return legs


def stays_from_items(items: list[dict]) -> list[dict]:
    """LodgingReservations in the stays importer's shape (schema.org conversion),
    with KItinerary's coordinates kept so the importer need not geocode."""
    from .schema_org import _reservation_to_stay

    stays: list[dict] = []
    for obj in items:
        if _type(obj) != "LodgingReservation":
            continue
        stay = _reservation_to_stay(obj)
        if stay is None:
            continue
        place = _place(obj.get("reservationFor"))
        stay["lat"], stay["lon"] = place["lat"], place["lon"]
        stays.append(stay)
    return stays


def rentals_from_items(items: list[dict]) -> list[dict]:
    """RentalCarReservations in the car-rental importer's shape."""
    rentals: list[dict] = []
    for obj in items:
        if _type(obj) != "RentalCarReservation" or _cancelled(obj):
            continue
        car = _dict(obj.get("reservationFor"))
        pickup, dropoff = _place(obj.get("pickupLocation")), _place(obj.get("dropoffLocation"))
        pickup_time, dropoff_time = (
            _local_time(obj.get("pickupTime")),
            _local_time(obj.get("dropoffTime")),
        )
        vendor = _str(car.get("rentalCompany")) or _str(obj.get("provider"))
        if not (vendor and pickup_time and dropoff_time):
            continue
        pickup_name = pickup["name"] or pickup["address"] or pickup["city"] or ""
        # No return location stated is not "the same counter": guessing an
        # endpoint is what the vendor readers in car_rental.py refuse too.
        dropoff_name = dropoff["name"] or dropoff["address"] or dropoff["city"] or ""
        if not pickup_name or not dropoff_name:
            continue
        vehicle = " ".join(
            p
            for p in (_str(car.get("brand")), _str(car.get("model")) or _str(car.get("name")))
            if p
        )
        rentals.append(
            {
                "vendor": vendor,
                "booking_reference": _str(obj.get("reservationNumber")) or None,
                "pickup_place": pickup_name,
                "pickup_datetime": pickup_time,
                "dropoff_place": dropoff_name,
                "dropoff_datetime": dropoff_time,
                "vehicle": vehicle or None,
                "driver_name": _str(obj.get("underName")) or None,
            }
        )
    return rentals


# reservation type -> (what is booked, where it is, when it starts)
_BOOKING_TYPES = {
    "EventReservation": ("reservationFor", "location", "startDate"),
    "FoodEstablishmentReservation": ("reservationFor", None, "startTime"),
    "TouristAttractionVisit": ("touristAttraction", None, "arrivalTime"),
}


def bookings_from_items(items: list[dict]) -> list[dict]:
    """Event, restaurant and attraction bookings as planner items.

    Each becomes a "booked" item on its own day: title, local date and time,
    the place's name and coordinates, the reservation number in the notes.
    Without a clock time there is no day to put it on, so it is skipped.
    """
    bookings: list[dict] = []
    seen: set[tuple] = set()
    for obj in items:
        spec = _BOOKING_TYPES.get(_type(obj))
        if spec is None or _cancelled(obj):
            continue
        what_key, where_key, when_key = spec
        what = _dict(obj.get(what_key))
        where = _place(what.get(where_key) if where_key else what)
        start = _local_time(what.get(when_key) or obj.get(when_key))
        title = _str(what.get("name")) or where["name"]
        if not (title and start):
            continue
        key = (title.lower(), start)
        if key in seen:  # one ticket per attendee
            continue
        seen.add(key)
        ref = _str(obj.get("reservationNumber"))
        bookings.append(
            {
                "title": title,
                "date": start[:10],
                "time": start[11:16],
                "place_name": where["name"] or None,
                "lat": where["lat"],
                "lon": where["lon"],
                "notes": f"Booking {ref}" if ref else None,
            }
        )
    return bookings


def extract_kitinerary_ground_legs(email_msg) -> list[dict]:
    return ground_legs_from_items(kitinerary_items(email_msg), _email_text(email_msg))


def extract_kitinerary_stays(email_msg) -> list[dict]:
    return stays_from_items(kitinerary_items(email_msg))


def extract_kitinerary_rentals(email_msg) -> list[dict]:
    return rentals_from_items(kitinerary_items(email_msg))


def extract_kitinerary_bookings(email_msg) -> list[dict]:
    return bookings_from_items(kitinerary_items(email_msg))
