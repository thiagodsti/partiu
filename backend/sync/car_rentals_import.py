"""Import car rentals confirmed by email into trips.

The parser (`parsers/car_rental.py`) turns a Hertz / Sixt / Europcar
confirmation into typed fields; this module decides which trip those fields
belong to, opening one when nothing fits. It is the third sibling of
`grouping.py` (flights) and `stays_import.py` (accommodation), and sits beside
them for the same reason: what a booking belongs to is a sync concern, not
something the `car_rentals` feature should know about.

**The trip match reuses the stay rule, widened by one term.** A rental matches
the trip whose *contents* fall inside its own span, plus `RENTAL_TRIP_WINDOW_DAYS`
of slack — but "contents" here means flights **and stays**, where
`stays_import` looks only at flights. That difference is deliberate and is the
whole point of the feature: a car is hired precisely on the trips that are not
built out of flights. The Europcar booking in the corpus is a Sicilian drive,
and a rule that could only see flights would be blind on exactly the itineraries
a rental defines.

**Imports create and never delete.** The same rule `stays_import` states: no
cancellation mail for a rental appeared anywhere in the corpus, so there is
nothing to parse for it, and two overlapping rentals on one trip is a visible
row the traveller can remove rather than silent corruption. (Cancellation is
handled for *flights*, where the airlines do send a parseable notice — see
`parsers/cancellations.py`.)
"""

import logging
import uuid
from datetime import date, timedelta

from ..database import db_conn, db_write
from ..parsers.car_rental import extract_car_rentals
from ..utils import now_iso

logger = logging.getLogger(__name__)

__all__ = ["RENTAL_TRIP_WINDOW_DAYS", "import_car_rentals_from_email"]

# Days of slack either side of the rental's own span when looking for its trip.
# Deliberately the same tight window `stays_import` measured its way to: the
# rental is collected and returned *inside* the trip, so slack buys little and
# every extra day is a chance to swallow a neighbouring trip.
RENTAL_TRIP_WINDOW_DAYS = 2


def _shift(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def _find_existing_rental(user_id: int, rental: dict) -> str | None:
    """The id of an already-imported copy of this booking, if any.

    Keyed on the booking reference where there is one — that is the booking's
    identity and survives the vendor restating it in a reminder. All three
    vendors print one, but the fallback (vendor plus pickup date) is kept for
    the same reason `stays_import` keeps its own: a layout that stops printing
    the reference must not start creating a duplicate on every sync.
    """
    pickup_date = rental["pickup_datetime"][:10]
    with db_conn() as conn:
        if rental.get("booking_reference"):
            row = conn.execute(
                """SELECT r.id FROM trip_car_rentals r JOIN trips t ON t.id = r.trip_id
                   WHERE t.user_id = ? AND r.booking_reference = ?""",
                (user_id, rental["booking_reference"]),
            ).fetchone()
            if row:
                return row["id"]
        row = conn.execute(
            """SELECT r.id FROM trip_car_rentals r JOIN trips t ON t.id = r.trip_id
               WHERE t.user_id = ? AND r.vendor = ? AND r.pickup_date = ?""",
            (user_id, rental["vendor"], pickup_date),
        ).fetchone()
        return row["id"] if row else None


def _find_trip_for_rental(user_id: int, rental: dict, country: str | None) -> str | None:
    """The trip whose flights or stays sit inside this rental's span, or None.

    Ambiguity is resolved by content count rather than refused, matching
    `stays_import._find_trip_for_stay`: picking the trip that contributes more
    of the itinerary beats creating a duplicate beside a perfectly good one.

    The country gate works the same way too, but it is **weaker on every side**,
    and deliberately. A stay's country comes from the platform's own markup; a
    rental's can only come from geocoding the counter, so it is absent more
    often and less trustworthy when present. So a NULL on *either* side passes:
    an unknown rental country, an airport with no `country_code` recorded (which
    is also what a missing `airports` row looks like through the LEFT JOIN), a
    stay whose country was never resolved. The gate only ever fires when both
    sides actually know, and then disagree. A missing signal must not block a
    true match — and the failure modes are not symmetric: joining the wrong trip
    puts a visible row on the wrong page, while refusing a true match silently
    creates a duplicate trip beside a perfectly good one.
    """
    lo = _shift(rental["pickup_datetime"][:10], -RENTAL_TRIP_WINDOW_DAYS)
    hi = _shift(rental["dropoff_datetime"][:10], RENTAL_TRIP_WINDOW_DAYS)
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT trip_id, COUNT(*) AS n, MIN(at) AS first_at FROM (
                   SELECT f.trip_id AS trip_id, f.departure_datetime AS at
                     FROM flights f
                     LEFT JOIN airports da ON da.iata_code = f.departure_airport
                     LEFT JOIN airports aa ON aa.iata_code = f.arrival_airport
                    WHERE f.user_id = ?
                      AND f.trip_id IS NOT NULL
                      AND DATE(f.departure_datetime) BETWEEN ? AND ?
                      AND (? IS NULL
                           OR da.country_code IS NULL OR aa.country_code IS NULL
                           OR da.country_code = ? OR aa.country_code = ?)
                   UNION ALL
                   SELECT s.trip_id AS trip_id, s.check_in_datetime AS at
                     FROM trip_stays s
                     JOIN trips t ON t.id = s.trip_id
                    WHERE t.user_id = ?
                      AND s.check_in_date BETWEEN ? AND ?
                      AND (? IS NULL OR s.country IS NULL OR s.country = ?)
               )
               GROUP BY trip_id
               ORDER BY n DESC, first_at""",
            (user_id, lo, hi, country, country, country, user_id, lo, hi, country, country),
        ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        logger.info(
            "Car rental import: %d trips match the %s rental; taking the one with most contents",
            len(rows),
            rental["vendor"],
        )
    return rows[0]["trip_id"]


def _trip_name_for_rental(rental: dict) -> str:
    """Name a trip after where the car was collected and when, matching the
    shape `grouping.py` and `stays_import.py` both use."""
    where = rental.get("pickup_place") or rental["vendor"]
    try:
        when = date.fromisoformat(rental["pickup_datetime"][:10]).strftime("%b %Y")
    except ValueError:
        when = ""
    return f"{where} ({when})" if when else where


def _create_trip_for_rental(user_id: int, rental: dict) -> str:
    """Open an auto-generated trip for a rental that matched no existing one.

    No planned dates are written, for the reason `stays_import` sets out: an
    auto-generated trip declares nothing and is described entirely by its
    contents, so the span comes from `_recompute_span` once the rental is
    attached — and a flight booked later widens it rather than fighting a
    declared pair.
    """
    trip_id = str(uuid.uuid4())
    name = _trip_name_for_rental(rental)
    now = now_iso()
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, is_auto_generated,
                                  user_id, created_at, updated_at)
               VALUES (?, ?, '[]', 1, ?, ?, ?)""",
            (trip_id, name, user_id, now, now),
        )
    logger.info("Car rental import: created trip '%s' (id=%s)", name, trip_id)
    return trip_id


def _geocode(place: str) -> tuple[float | None, float | None, str | None]:
    """Resolve a rental counter so the leg gets a map pin, a zone and a country.

    Without a geocoder the rental still saves: it simply has no pin, its times
    are stored as typed, and it contributes no country — the documented
    behaviour for every hand-entered place in this codebase.
    """
    from ..integrations.photon import client as photon

    try:
        results = photon.search_places(place, kind="stay", limit=1)
    except Exception as exc:  # noqa: BLE001 - a geocoder outage must not lose the booking
        logger.warning("Car rental import: geocoding failed for %r: %s", place[:60], exc)
        return None, None, None
    if not results:
        return None, None, None
    top = results[0]
    return top.get("lat"), top.get("lon"), (top.get("countrycode") or "").upper() or None


def import_car_rentals_from_email(email_msg, user_id: int) -> list[str]:
    """Create car rentals for every booking this email confirms.

    Returns the ids created — empty for the overwhelming majority of mail, which
    is not from a rental company at all.
    """
    from ..car_rentals.service import car_rental_service

    rentals = extract_car_rentals(email_msg)
    if not rentals:
        return []

    created: list[str] = []
    for rental in rentals:
        try:
            if _find_existing_rental(user_id, rental):
                logger.debug(
                    "Car rental import: %s %s already imported",
                    rental["vendor"],
                    rental.get("booking_reference", ""),
                )
                continue

            pickup_lat, pickup_lon, pickup_country = _geocode(rental["pickup_place"])
            if rental["dropoff_place"] == rental["pickup_place"]:
                dropoff_lat, dropoff_lon, dropoff_country = pickup_lat, pickup_lon, pickup_country
            else:
                dropoff_lat, dropoff_lon, dropoff_country = _geocode(rental["dropoff_place"])

            trip_id = _find_trip_for_rental(
                user_id, rental, pickup_country
            ) or _create_trip_for_rental(user_id, rental)

            rental_id = car_rental_service.create_rental(
                trip_id,
                user_id,
                {
                    "vendor": rental["vendor"],
                    "pickup": {
                        "name": rental["pickup_place"],
                        "lat": pickup_lat,
                        "lon": pickup_lon,
                        "country_code": pickup_country,
                    },
                    "dropoff": {
                        "name": rental["dropoff_place"],
                        "lat": dropoff_lat,
                        "lon": dropoff_lon,
                        "country_code": dropoff_country,
                    },
                    "pickup_datetime": rental["pickup_datetime"],
                    "dropoff_datetime": rental["dropoff_datetime"],
                    "booking_reference": rental.get("booking_reference"),
                    "vehicle": rental.get("vehicle"),
                    "driver_name": rental.get("driver_name"),
                },
            )
            created.append(rental_id)
            logger.info(
                "User %d: imported %s rental %s → %s into trip %s",
                user_id,
                rental["vendor"],
                rental["pickup_datetime"][:10],
                rental["dropoff_datetime"][:10],
                trip_id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad booking must not stop the sync
            logger.error(
                "User %d: failed to import %s rental: %s",
                user_id,
                rental.get("vendor"),
                exc,
                exc_info=True,
            )

    return created
