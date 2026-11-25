"""Import what KDE Itinerary reads beyond flights: ground legs and bookings.

``parsers/kitinerary.py`` turns its JSON-LD into typed dicts; this module
decides where they go, on the same footing as ``stays_import`` and
``car_rentals_import`` (KItinerary's stays and rentals go through those two
importers directly, as their last-resort reader).

**Train, bus and ferry legs** become ``trip_segments``. Every leg of one email
goes to one trip — a booking with an outbound and a return is one journey — and
that trip is, in order of evidence:

1. the trip already holding a leg with the same booking reference (a return
   ticket mailed separately);
2. the trip whose contents — flights, legs, stays, rentals — fall within
   ``LEG_TRIP_WINDOW_DAYS`` of the legs, most contents first: the same rule the
   stays and rentals importers use, widened to every kind of content;
3. the shortest trip whose dates contain the legs;
4. otherwise a new trip, named after where the first leg arrives. Decided with
   the user: a train weekend is a trip, even within one country or city.

**Event, restaurant and attraction bookings** become "booked" items in the
trip planner, on their own day, which the trip page's day cards show too. They
**never create a trip**: a concert in your own city is not one. A booking with
no trip covering its day is skipped.

Both are idempotent and only ever add, like every importer here: the same leg
(type, departure place, local departure minute and number) or the same booking
(any of the user's trips, day, title) is not created twice, and nothing is
deleted.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..database import db_conn, db_write
from ..parsers.kitinerary import extract_kitinerary_bookings, extract_kitinerary_ground_legs
from ..utils import now_iso

logger = logging.getLogger(__name__)

__all__ = ["LEG_TRIP_WINDOW_DAYS", "import_kitinerary_bookings", "import_kitinerary_ground_legs"]

# Same slack as stays_import.STAY_TRIP_WINDOW_DAYS, for the same measured reason.
LEG_TRIP_WINDOW_DAYS = 2


def _shift(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Ground legs
# ---------------------------------------------------------------------------


def _local_wall_clock(utc_iso: str, timezone: str | None) -> str:
    """A stored UTC instant as wall clock at its own place ("2026-03-13T07:30").

    A leg saved without a timezone (no coordinates) was stored as typed, so its
    stored value already is the wall clock.
    """
    stamp = datetime.fromisoformat(utc_iso)
    if timezone:
        try:
            stamp = stamp.astimezone(ZoneInfo(timezone))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return stamp.replace(tzinfo=None).isoformat(timespec="minutes")


def _existing_leg_trip(user_id: int, leg: dict) -> str | None:
    """The trip already holding this exact leg, or None.

    The same type, departure place, local departure minute and (when both
    sides have one) service number. Exact, not "same day": SJ 10 runs every
    day, and the March 14 departure is a different leg from the March 13 one.
    The stored instant is UTC, so the ±1 day SQL window only narrows the
    candidates; the comparison is on each one's own local wall clock.
    """
    day = leg["departure_datetime"][:10]
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT s.trip_id, s.departure_datetime, s.departure_timezone, s.number
                 FROM trip_segments s JOIN trips t ON t.id = s.trip_id
                WHERE t.user_id = ? AND s.type = ?
                  AND LOWER(s.departure_place) = LOWER(?)
                  AND DATE(s.departure_datetime) BETWEEN ? AND ?""",
            (user_id, leg["type"], leg["departure"]["name"], _shift(day, -1), _shift(day, 1)),
        ).fetchall()
    for row in rows:
        if row["number"] and leg.get("number") and row["number"] != leg["number"]:
            continue
        if (
            _local_wall_clock(row["departure_datetime"], row["departure_timezone"])
            == leg["departure_datetime"][:16]
        ):
            return row["trip_id"]
    return None


def _trip_by_reference(user_id: int, reference: str | None) -> str | None:
    if not reference:
        return None
    with db_conn() as conn:
        row = conn.execute(
            """SELECT s.trip_id FROM trip_segments s JOIN trips t ON t.id = s.trip_id
               WHERE t.user_id = ? AND s.booking_reference = ? LIMIT 1""",
            (user_id, reference),
        ).fetchone()
    return row["trip_id"] if row else None


def _trip_by_contents(user_id: int, first_day: str, last_day: str) -> str | None:
    """The trip with the most contents within the window around the legs."""
    lo = _shift(first_day, -LEG_TRIP_WINDOW_DAYS)
    hi = _shift(last_day, LEG_TRIP_WINDOW_DAYS)
    with db_conn() as conn:
        row = conn.execute(
            """SELECT trip_id, COUNT(*) AS n FROM (
                   SELECT f.trip_id FROM flights f
                    WHERE f.user_id = ? AND f.trip_id IS NOT NULL
                      AND DATE(f.departure_datetime) BETWEEN ? AND ?
                   UNION ALL
                   SELECT s.trip_id FROM trip_segments s JOIN trips t ON t.id = s.trip_id
                    WHERE t.user_id = ? AND DATE(s.departure_datetime) BETWEEN ? AND ?
                   UNION ALL
                   SELECT st.trip_id FROM trip_stays st JOIN trips t ON t.id = st.trip_id
                    WHERE t.user_id = ? AND st.check_in_date <= ? AND st.check_out_date >= ?
                   UNION ALL
                   SELECT r.trip_id FROM trip_car_rentals r JOIN trips t ON t.id = r.trip_id
                    WHERE t.user_id = ? AND r.pickup_date <= ? AND r.dropoff_date >= ?
               )
               GROUP BY trip_id
               ORDER BY n DESC
               LIMIT 1""",
            (user_id, lo, hi, user_id, lo, hi, user_id, hi, lo, user_id, hi, lo),
        ).fetchone()
    return row["trip_id"] if row else None


def _trip_containing(user_id: int, first_day: str, last_day: str) -> str | None:
    """The shortest of the user's trips whose dates contain the span."""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT id FROM trips
               WHERE user_id = ? AND start_date IS NOT NULL AND end_date IS NOT NULL
                 AND start_date <= ? AND end_date >= ?
               ORDER BY julianday(end_date) - julianday(start_date)
               LIMIT 1""",
            (user_id, first_day, last_day),
        ).fetchone()
    return row["id"] if row else None


def _create_trip(user_id: int, leg: dict) -> str:
    """An auto-generated trip named after where the journey arrives, matching
    the shape the other importers use ("Oslo S (Mar 2026)")."""
    where = leg["arrival"]["city"] or leg["arrival"]["name"]
    try:
        when = date.fromisoformat(leg["departure_datetime"][:10]).strftime("%b %Y")
    except ValueError:
        when = ""
    name = f"{where} ({when})" if when else where
    trip_id = str(uuid.uuid4())
    now = now_iso()
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, is_auto_generated,
                                  user_id, created_at, updated_at)
               VALUES (?, ?, '[]', 1, ?, ?, ?)""",
            (trip_id, name, user_id, now, now),
        )
    logger.info("KItinerary import: created trip '%s' (id=%s)", name, trip_id)
    return trip_id


def _geocode(place: dict, kind: str) -> dict:
    """Fill a station's coordinates (and country, when missing) from Photon.

    KItinerary knows many stations' coordinates; for the rest the station
    picker's own lookup is used. Without a geocoder the leg still saves, with no
    map line and its times stored as typed — the documented behaviour for any
    hand-typed place.
    """
    if place["lat"] is not None and place["lon"] is not None:
        return place
    from ..integrations.photon import client as photon

    try:
        results = photon.search_stations(place["name"], kind=kind, limit=1)
    except Exception as exc:  # noqa: BLE001 - a geocoder outage must not lose the leg
        logger.warning("KItinerary import: geocoding failed for %r: %s", place["name"][:60], exc)
        return place
    if not results:
        return place
    top = results[0]
    return {
        **place,
        "lat": top.get("lat"),
        "lon": top.get("lon"),
        "country_code": place["country_code"] or ((top.get("countrycode") or "").upper() or None),
    }


def import_kitinerary_ground_legs(email_msg, user_id: int) -> list[str]:
    """Create the train, bus and ferry legs this email books. Returns their ids.

    The whole journey decides the trip — legs already imported included — and
    only the missing legs are created. A leg already on a trip anchors the rest
    of its email to that trip, so a return re-read after its outbound was saved
    (or a retry after a partial save) does not open a second trip. Legs are
    validated before any trip is chosen or created, so an email whose legs all
    fail validation leaves no empty trip behind.
    """
    from ..segments.service import segment_service

    journey = sorted(
        extract_kitinerary_ground_legs(email_msg), key=lambda leg: leg["departure_datetime"]
    )
    if not journey:
        return []

    anchor_trip: str | None = None
    payloads: list[tuple[dict, dict]] = []
    for leg in journey:
        existing = _existing_leg_trip(user_id, leg)
        if existing:
            anchor_trip = anchor_trip or existing
            continue
        data = {
            "type": leg["type"],
            "operator": leg.get("operator"),
            "number": leg.get("number"),
            "booking_reference": leg.get("booking_reference"),
            "departure": _geocode(leg["departure"], leg["type"]),
            "arrival": _geocode(leg["arrival"], leg["type"]),
            "departure_datetime": leg["departure_datetime"],
            "arrival_datetime": leg["arrival_datetime"],
            "seat": leg.get("seat"),
        }
        try:
            segment_service.validate_segment(data)
        except ValueError as exc:
            logger.info("KItinerary import: skipping a %s leg: %s", leg["type"], exc)
            continue
        payloads.append((leg, data))
    if not payloads:
        return []

    first_day = journey[0]["departure_datetime"][:10]
    last_day = max(leg["arrival_datetime"][:10] for leg in journey)
    try:
        trip_id = (
            anchor_trip
            or next(
                (
                    t
                    for t in (
                        _trip_by_reference(user_id, leg["booking_reference"]) for leg in journey
                    )
                    if t
                ),
                None,
            )
            or _trip_by_contents(user_id, first_day, last_day)
            or _trip_containing(user_id, first_day, last_day)
            or _create_trip(user_id, journey[0])
        )
    except Exception as exc:  # noqa: BLE001 - one bad booking must not stop the sync
        logger.error("User %d: KItinerary trip matching failed: %s", user_id, exc, exc_info=True)
        return []

    created: list[str] = []
    for leg, data in payloads:
        try:
            segment_id = segment_service.create_segment(trip_id, user_id, data)
            created.append(segment_id)
            logger.info(
                "User %d: imported %s %s → %s (%s) into trip %s",
                user_id,
                leg["type"],
                leg["departure"]["name"][:30],
                leg["arrival"]["name"][:30],
                leg["departure_datetime"][:10],
                trip_id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad leg must not stop the sync
            logger.error("User %d: failed to import a %s leg: %s", user_id, leg["type"], exc)
    return created


# ---------------------------------------------------------------------------
# Bookings → planner items
# ---------------------------------------------------------------------------


def _existing_item(user_id: int, booking: dict) -> bool:
    """Whether this booking is already in one of the user's planners.

    Checked across every trip, before a trip is chosen: if a shorter trip
    covering the day appears after the first import, a re-read must not add a
    second copy there while the first stays where it was put.
    """
    with db_conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM trip_plan_items i JOIN trips t ON t.id = i.trip_id
               WHERE t.user_id = ? AND i.date = ? AND LOWER(i.title) = LOWER(?) LIMIT 1""",
            (user_id, booking["date"], booking["title"]),
        ).fetchone()
    return row is not None


def import_kitinerary_bookings(email_msg, user_id: int) -> list[str]:
    """Add the email's event, restaurant and attraction bookings to the planner
    of the trip covering their day. Never creates a trip. Returns item ids."""
    from ..planner.service import planner_service

    created: list[str] = []
    for booking in extract_kitinerary_bookings(email_msg):
        try:
            if _existing_item(user_id, booking):
                continue
            trip_id = _trip_containing(user_id, booking["date"], booking["date"])
            if trip_id is None:
                logger.info(
                    "KItinerary import: no trip covers %s on %s; not creating one for a booking",
                    booking["title"][:40],
                    booking["date"],
                )
                continue
            item_id = planner_service.create_item(trip_id, user_id, {**booking, "status": "booked"})
            created.append(item_id)
            logger.info(
                "User %d: added booking '%s' on %s to trip %s",
                user_id,
                booking["title"][:40],
                booking["date"],
                trip_id,
            )
        except Exception as exc:  # noqa: BLE001 - one bad booking must not stop the sync
            logger.error("User %d: failed to add a booking: %s", user_id, exc)
    return created
