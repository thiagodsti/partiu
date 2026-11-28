"""Import accommodation from booking emails into trips.

The parsers (``parsers/schema_org.py`` for typed markup, ``parsers/booking_com.py``
and ``parsers/trip_com.py`` for the Booking.com and Trip.com templates, which carry none) turn a booking email into typed fields;
this module decides which trip those fields belong to, creating one when no
trip fits. It is the accommodation counterpart of ``grouping.py`` and lives
beside it for the same reason: deciding what a booking belongs to is a sync
concern, not something the stays feature should know about.

**The matching rule was measured, not guessed.** Against nine years of real
mail (six bookings, 74 flights), a stay matches the trip whose flights fall
within its own span — outbound arriving on the check-in day, return departing
on the check-out day — and `STAY_TRIP_WINDOW_DAYS` of slack around it. Five of six
bookings found exactly one trip that way, and the answer did not change
anywhere between ±0 and ±21 days; only at ±30 did a stay start touching two
trips. The window is therefore small on purpose: the slack buys nothing that ±0
did not already find, and every extra day is a chance to swallow a neighbouring
trip. The sixth booking had no flights within a month in either direction — a
drive to Italy — which is the case trip creation exists for.

**A stay inside a trip's span joins it** when no flight is near it: the flight
window only finds the stays at a trip's ends, where the traveller flies in or
out, so a night in Xi'an in the middle of a Stockholm → Beijing fortnight opened
a trip of its own. See ``_find_trip_containing_stay``. The country gate below
does not apply to it: a trip that covers both nights is the trip the traveller
is on, wherever the hotel is.

**Bracketing was considered and dropped.** The intuition is that a stay sits
between an outbound and a return, so a stay-trip should adopt flights falling
*outside* its span. Real itineraries do not look like that: the traveller flies
in on the day they check in and out on the day they check out, so the flights
are *inside* the stay, and plain span overlap finds them.

**The country gate is free insurance.** The markup names the property's country
and the airports table names each airport's, so a stay only joins a trip that
touched its country. It never once blocked a true match in the corpus, and it
is what stops a Lisbon weekend being absorbed by a Tokyo trip whose flights
fall near it. It guards the flight window only: a stay wholly inside a trip's
span joins that trip regardless.

What this cannot do is **remove** a booking. No cancellation or alteration mail
appeared anywhere in the corpus, so there is nothing to parse for it; in the
one case where a booking was clearly cancelled and rebooked, the only evidence
was a second confirmation for the same nights at a different property. Imports
therefore create stays and never delete them, and two overlapping stays on one
trip is a visible row the traveller can remove rather than silent corruption.

**A stated price becomes an expense.** Trip.com and Booking.com print what the
booking cost (schema.org markup can too, though no measured Airbnb record
does), and that is money the trip has already spent. The importer records it on
the stay (`price_amount` / `price_currency`) and adds an expense named after the
property, paid by and split to the importing user alone: who else shares a
room is not something the mail says, and an expense charged to companions who
never agreed to it would move their balances. The traveller can split it later.
The recorded price is the idempotency marker: a stay imported before prices
were read gets its expense on the next parse of its mail (a rescan), and a
deleted expense never comes back, because the price is already on the stay.
"""

import logging
import uuid
from datetime import date, timedelta

from ..database import db_conn, db_write
from ..integrations.photon import client as photon
from ..parsers.booking_com import extract_booking_com_stays
from ..parsers.kitinerary import extract_kitinerary_stays
from ..parsers.schema_org import extract_lodging_reservations
from ..parsers.trip_com import extract_trip_com_stays
from ..utils import now_iso
from .stay_geocode import geocode_stay

logger = logging.getLogger(__name__)

__all__ = ["STAY_TRIP_WINDOW_DAYS", "import_lodging_from_email"]

# Days of slack either side of the stay's own span when looking for its trip.
# See the module docstring: ±0 already found every match, so this is deliberately
# tight rather than generous. Public because `grouping.py` matches in the
# opposite direction — flights arriving after the stay — and the two must agree
# or a booking would find a trip going one way but not coming back.
STAY_TRIP_WINDOW_DAYS = 2

# Which stay kind an email implies. Everything unrecognised is a hotel, which is
# the common case and the neutral one — `STAY_KINDS` has no "unknown".
_KIND_BY_DOMAIN = (
    ("airbnb.", "airbnb"),
    ("hostelworld.", "hostel"),
)


def _kind_for_sender(sender: str) -> str:
    lowered = (sender or "").lower()
    for needle, kind in _KIND_BY_DOMAIN:
        if needle in lowered:
            return kind
    return "hotel"


def _shift(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def _find_existing_stay(user_id: int, stay: dict):
    """Return the already-imported copy of this booking (id, trip_id,
    price_amount), if any.

    Idempotency is keyed on the booking reference where there is one, because
    that is the booking's identity and survives the platform restating it in a
    reminder. Where there is none — one real record in six had neither a
    reference nor a property name — the fallback is the property name plus the
    check-in date, which is the next best thing the traveller would recognise as
    "the same booking".
    """
    check_in_date = stay["check_in_datetime"][:10]
    with db_conn() as conn:
        if stay.get("booking_reference"):
            row = conn.execute(
                """SELECT s.id, s.trip_id, s.price_amount
                     FROM trip_stays s JOIN trips t ON t.id = s.trip_id
                   WHERE t.user_id = ? AND s.booking_reference = ?""",
                (user_id, stay["booking_reference"]),
            ).fetchone()
            if row:
                return row
        return conn.execute(
            """SELECT s.id, s.trip_id, s.price_amount
                 FROM trip_stays s JOIN trips t ON t.id = s.trip_id
               WHERE t.user_id = ? AND s.name = ? AND s.check_in_date = ?""",
            (user_id, stay["name"], check_in_date),
        ).fetchone()


def _record_price(user_id: int, stay_id: str, trip_id: str, stay: dict) -> str | None:
    """Write the mail's price on the stay and add it to the trip's expenses.

    Returns the expense id, or None when the mail states no price. The caller
    only calls this for a stay with no price recorded yet; see the module
    docstring for why that is the marker.
    """
    from ..expenses.service import ExpenseService

    price = stay.get("price")
    if not price:
        return None
    amount, currency = price
    with db_write() as conn:
        claimed = conn.execute(
            """UPDATE trip_stays SET price_amount = ?, price_currency = ?
                WHERE id = ? AND price_amount IS NULL""",
            (amount, currency, stay_id),
        ).rowcount
    if not claimed:
        return None
    me = ("user", user_id)
    try:
        expense_id = ExpenseService().create_expense(
            trip_id, user_id, stay["name"], amount, currency, paid_by=me, participants=[me]
        )
    except Exception:
        # Without its expense the price must not stay recorded, or the next
        # parse of this mail would take the missing expense as deleted.
        with db_write() as conn:
            conn.execute(
                "UPDATE trip_stays SET price_amount = NULL, price_currency = NULL WHERE id = ?",
                (stay_id,),
            )
        raise
    logger.info(
        "User %d: added %.2f %s for stay '%s' to the expenses of trip %s",
        user_id,
        amount,
        currency,
        stay["name"][:40],
        trip_id,
    )
    return expense_id


def _find_trip_for_stay(user_id: int, stay: dict) -> str | None:
    """The trip whose flights sit inside this stay's span, or None.

    Ambiguity is resolved by flight count rather than refused: at this window
    two trips never both matched in the measured corpus, but if it ever happens
    the trip contributing more of the itinerary is the better guess, and picking
    one beats creating a duplicate trip beside a perfectly good one.
    """
    lo = _shift(stay["check_in_datetime"][:10], -STAY_TRIP_WINDOW_DAYS)
    hi = _shift(stay["check_out_datetime"][:10], STAY_TRIP_WINDOW_DAYS)
    country = stay.get("country_code")
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT f.trip_id AS trip_id, COUNT(*) AS n
                 FROM flights f
                 LEFT JOIN airports da ON da.iata_code = f.departure_airport
                 LEFT JOIN airports aa ON aa.iata_code = f.arrival_airport
                WHERE f.user_id = ?
                  AND f.trip_id IS NOT NULL
                  AND DATE(f.departure_datetime) BETWEEN ? AND ?
                  AND (? IS NULL OR da.country_code = ? OR aa.country_code = ?)
                GROUP BY f.trip_id
                ORDER BY n DESC, MIN(f.departure_datetime)""",
            (user_id, lo, hi, country, country, country),
        ).fetchall()
    if not rows:
        return _find_trip_containing_stay(user_id, stay)
    if len(rows) > 1:
        logger.info(
            "Lodging import: %d trips match stay '%s'; taking the one with most flights",
            len(rows),
            stay["name"][:40],
        )
    return rows[0]["trip_id"]


def _find_trip_containing_stay(user_id: int, stay: dict) -> str | None:
    """The trip whose span holds the whole stay, when no flight is near it.

    The flight window finds a stay at either end of a trip, where the traveller
    flies in or out. A stay in the middle of a long one has no flight anywhere
    near: a Xi'an night on 27 March 2027, inside a Stockholm → Beijing trip of
    23 March to 9 April, found nothing and opened a trip of its own. A traveller
    is on one trip at a time, so a trip that already covers both nights is
    where the stay belongs, whatever its country: no country gate here, since a
    trip covering those dates is the trip the traveller is on (a train from
    Beijing to Hong Kong crosses into another country code on the same trip).
    The flight window keeps its gate, because there the trip is only near the
    stay. Trips should not overlap; if two do, the shortest is the most
    specific, and a stay belongs to one trip, so it takes that one.
    """
    check_in = stay["check_in_datetime"][:10]
    check_out = stay["check_out_datetime"][:10]
    with db_conn() as conn:
        row = conn.execute(
            """SELECT t.id AS trip_id
                 FROM trips t
                WHERE t.user_id = ?
                  AND t.start_date IS NOT NULL AND t.end_date IS NOT NULL
                  AND t.start_date <= ? AND t.end_date >= ?
                ORDER BY julianday(t.end_date) - julianday(t.start_date), t.start_date
                LIMIT 1""",
            (user_id, check_in, check_out),
        ).fetchone()
    if row:
        logger.info(
            "Lodging import: stay '%s' falls inside trip %s; joining it",
            stay["name"][:40],
            row["trip_id"],
        )
    return row["trip_id"] if row else None


def _trip_name_for_stay(stay: dict) -> str:
    """Name a trip after where it goes and when, matching grouping.py's shape."""
    where = stay.get("city") or stay["name"]
    try:
        when = date.fromisoformat(stay["check_in_datetime"][:10]).strftime("%b %Y")
    except ValueError:
        when = ""
    return f"{where} ({when})" if when else where


def _create_trip_for_stay(user_id: int, stay: dict) -> str:
    """Open an auto-generated trip for a booking that matched no existing one.

    No `planned_start_date` / `planned_end_date` is written: an auto-generated
    trip declares nothing and is described entirely by its contents, so the span
    comes from `_recompute_span` once the stay is attached. That is also what
    lets a flight arriving months later widen it rather than fight a declared
    pair — which is not hypothetical, as two of the measured bookings were made
    four and seven months before their flights were.
    """
    trip_id = str(uuid.uuid4())
    now = now_iso()
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, is_auto_generated,
                                  user_id, created_at, updated_at)
               VALUES (?, ?, '[]', 1, ?, ?, ?)""",
            (trip_id, _trip_name_for_stay(stay), user_id, now, now),
        )
    logger.info("Lodging import: created trip '%s' (id=%s)", _trip_name_for_stay(stay), trip_id)
    return trip_id


def _geocode(stay: dict) -> tuple[float | None, float | None, str | None]:
    """Resolve the property's coordinates so the stay gets a map pin and a zone.

    KDE Itinerary's stays can arrive with coordinates; everything else is looked
    up from the address, and kept only when the booking backs the answer up
    (``stay_geocode``). Without a geocoder, or with no answer that fits, the
    stay still saves: no pin, times stored as typed — the documented behaviour
    for a hand-entered place.
    """
    if stay.get("lat") is not None and stay.get("lon") is not None:
        return stay["lat"], stay["lon"], None
    if not photon.is_configured():
        return None, None, None
    return geocode_stay(stay)


def _place_existing(user_id: int, existing, stay: dict) -> None:
    """Give an already-imported stay the pin it never got.

    Stays imported while the geocoder was down — or before the checks above
    could find a Chinese street — have no position; reading the mail again
    (every rescan does) is the chance to place them. Only a stay still without
    one, so a place the traveller picked by hand is never overwritten. The
    stored times go back through the service with the new position, which
    re-localises them in the property's timezone.
    """
    from ..stays.repository import StayRepository
    from ..stays.service import stay_service

    stored = StayRepository().get(existing["id"], existing["trip_id"])
    if stored is None or stored.place.lat is not None:
        return
    lat, lon, geo_country = _geocode(stay)
    if lat is None or lon is None:
        return
    stay_service.update_stay(
        existing["trip_id"],
        existing["id"],
        user_id,
        {
            "place": {
                "name": stored.place.name,
                "address": stored.place.address,
                "lat": lat,
                "lon": lon,
                "country_code": stored.place.country_code
                or stay.get("country_code")
                or geo_country,
            },
            # Stored without a zone, so the wall clock as typed (or as mailed).
            "check_in_datetime": stored.check_in_datetime[:16],
            "check_out_datetime": stored.check_out_datetime[:16],
        },
    )
    logger.info("User %d: placed stay '%s' on the map", user_id, stored.place.name[:40])


def import_lodging_from_email(email_msg, user_id: int) -> list[str]:
    """Create stays for every lodging reservation this email declares.

    Returns the ids created — empty for the overwhelming majority of mail, which
    carries no markup at all.
    """
    from ..stays.service import stay_service

    # Markup first: a typed reservation is the stronger evidence. Booking.com
    # and Trip.com ship none, so their template readers are the fallback, each
    # gated on its own sender. KDE Itinerary's extractors come last: they cover
    # hotel chains and platforms we have no reader for.
    reservations = (
        extract_lodging_reservations(email_msg)
        or extract_booking_com_stays(email_msg)
        or extract_trip_com_stays(email_msg)
        or extract_kitinerary_stays(email_msg)
    )
    if not reservations:
        return []

    kind = _kind_for_sender(getattr(email_msg, "sender", "") or "")
    created: list[str] = []

    for stay in reservations:
        try:
            existing = _find_existing_stay(user_id, stay)
            if existing:
                logger.debug("Lodging import: '%s' already imported", stay["name"][:40])
                if existing["price_amount"] is None:
                    _record_price(user_id, existing["id"], existing["trip_id"], stay)
                _place_existing(user_id, existing, stay)
                continue

            lat, lon, geo_country = _geocode(stay)
            trip_id = _find_trip_for_stay(user_id, stay) or _create_trip_for_stay(user_id, stay)

            stay_id = stay_service.create_stay(
                trip_id,
                user_id,
                {
                    "kind": kind,
                    "place": {
                        "name": stay["name"],
                        "address": stay.get("address"),
                        "lat": lat,
                        "lon": lon,
                        # The platform's own country wins over the geocoder's:
                        # it is a fact the booking carries, not a lookup.
                        "country_code": stay.get("country_code") or geo_country,
                    },
                    "check_in_datetime": stay["check_in_datetime"],
                    "check_out_datetime": stay["check_out_datetime"],
                    "booking_reference": stay.get("booking_reference"),
                    "contact": stay.get("contact"),
                    "room_type": stay.get("room_type"),
                    "guests": stay.get("guests"),
                },
            )
            created.append(stay_id)
            _record_price(user_id, stay_id, trip_id, stay)
            logger.info(
                "User %d: imported stay '%s' (%s → %s) into trip %s",
                user_id,
                stay["name"][:40],
                stay["check_in_datetime"][:10],
                stay["check_out_datetime"][:10],
                trip_id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad booking must not stop the sync
            logger.error(
                "User %d: failed to import lodging '%s': %s",
                user_id,
                str(stay.get("name"))[:40],
                exc,
                exc_info=True,
            )

    return created
