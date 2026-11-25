"""Tests for `sync/kitinerary_import.py` — where KDE Itinerary's ground legs and
bookings go.

The converters are tested in `test_kitinerary.py`; here they are stubbed and
what is checked is the placing: which trip a train joins, when one is created,
that a booking never creates one, and that a second read adds nothing.
"""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from backend.sync import kitinerary_import

_n = itertools.count(1)


def _user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, 'h', 0)",
        (f"kitimport{next(_n)}",),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _trip(db_path: str, user_id: int, name="Trip", start=None, end=None) -> str:
    trip_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trips (id, user_id, name, is_auto_generated, booking_refs,
                              start_date, end_date, created_at, updated_at)
           VALUES (?, ?, ?, 1, '[]', ?, ?, ?, ?)""",
        (trip_id, user_id, name, start, end, now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


def _flight(db_path: str, user_id: int, trip_id: str, dep: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO flights (id, user_id, trip_id, flight_number, departure_airport,
                                departure_datetime, arrival_airport, arrival_datetime,
                                created_at, updated_at)
           VALUES (?, ?, ?, 'SK1', 'ARN', ?, 'OSL', ?, 'x', 'x')""",
        (str(uuid.uuid4()), user_id, trip_id, dep, dep),
    )
    conn.commit()
    conn.close()


def _rows(db_path: str, sql: str, *args):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _place(name, city=None, lat=59.33, lon=18.06, country="SE"):
    return {
        "name": name,
        "city": city,
        "lat": lat,
        "lon": lon,
        "country_code": country,
        "address": None,
    }


def _leg(
    dep="Stockholm C",
    arr="Oslo S",
    when="2026-03-13T07:30",
    until="2026-03-13T12:30",
    ref="SJ123",
    number="SJ 10",
):
    return {
        "type": "train",
        "operator": "SJ",
        "number": number,
        "booking_reference": ref,
        "departure": _place(dep, "Stockholm"),
        "arrival": _place(arr, "Oslo", lat=59.91, lon=10.75, country="NO"),
        "departure_datetime": when,
        "arrival_datetime": until,
        "seat": "Coach 3, seat 12",
    }


def _import_legs(user_id, legs):
    with patch.object(kitinerary_import, "extract_kitinerary_ground_legs", return_value=legs):
        return kitinerary_import.import_kitinerary_ground_legs(object(), user_id)


def _import_bookings(user_id, bookings):
    with patch.object(kitinerary_import, "extract_kitinerary_bookings", return_value=bookings):
        return kitinerary_import.import_kitinerary_bookings(object(), user_id)


class TestGroundLegs:
    def test_a_train_with_nothing_near_it_opens_a_trip(self, test_db):
        user_id = _user(test_db)
        (seg_id,) = _import_legs(user_id, [_leg()])

        (seg,) = _rows(test_db, "SELECT * FROM trip_segments WHERE id = ?", seg_id)
        (trip,) = _rows(test_db, "SELECT * FROM trips WHERE id = ?", seg["trip_id"])
        assert trip["name"] == "Oslo (Mar 2026)"
        assert trip["is_auto_generated"] == 1
        assert (seg["type"], seg["number"], seg["seat"]) == ("train", "SJ 10", "Coach 3, seat 12")
        assert (seg["departure_country"], seg["arrival_country"]) == ("SE", "NO")
        # 07:30 in Stockholm (CET) is 06:30 UTC: localised from the coordinates.
        assert seg["departure_datetime"].startswith("2026-03-13T06:30")
        # The span now covers the leg, so the day planner has a card for it.
        assert (trip["start_date"], trip["end_date"]) == ("2026-03-13", "2026-03-13")

    def test_outbound_and_return_in_one_email_share_a_trip(self, test_db):
        user_id = _user(test_db)
        ids = _import_legs(
            user_id,
            [
                _leg(),
                _leg(
                    "Oslo S", "Stockholm C", "2026-03-15T17:00", "2026-03-15T22:00", number="SJ 11"
                ),
            ],
        )
        trips = {r["trip_id"] for r in _rows(test_db, "SELECT trip_id FROM trip_segments")}
        assert len(ids) == 2 and len(trips) == 1

    def test_a_train_joins_the_trip_its_flights_belong_to(self, test_db):
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id, "Oslo weekend")
        _flight(test_db, user_id, trip_id, "2026-03-12T08:00:00+00:00")

        (seg_id,) = _import_legs(user_id, [_leg()])
        (seg,) = _rows(test_db, "SELECT trip_id FROM trip_segments WHERE id = ?", seg_id)
        assert seg["trip_id"] == trip_id
        assert len(_rows(test_db, "SELECT id FROM trips WHERE user_id = ?", user_id)) == 1

    def test_a_return_mailed_separately_joins_by_booking_reference(self, test_db):
        user_id = _user(test_db)
        (first,) = _import_legs(user_id, [_leg()])
        (second,) = _import_legs(
            user_id,
            [_leg("Oslo S", "Stockholm C", "2026-04-20T17:00", "2026-04-20T22:00", number="SJ 11")],
        )
        trips = {r["trip_id"] for r in _rows(test_db, "SELECT trip_id FROM trip_segments")}
        assert len(trips) == 1, "five weeks apart, but the same booking"

    def test_a_train_inside_a_trip_s_dates_joins_it(self, test_db):
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id, "Scandinavia", start="2026-03-01", end="2026-03-31")
        (seg_id,) = _import_legs(user_id, [_leg(ref=None)])
        (seg,) = _rows(test_db, "SELECT trip_id FROM trip_segments WHERE id = ?", seg_id)
        assert seg["trip_id"] == trip_id

    def test_reading_the_email_again_adds_nothing(self, test_db):
        user_id = _user(test_db)
        assert len(_import_legs(user_id, [_leg()])) == 1
        assert _import_legs(user_id, [_leg()]) == []
        assert len(_rows(test_db, "SELECT id FROM trip_segments")) == 1
        assert len(_rows(test_db, "SELECT id FROM trips WHERE user_id = ?", user_id)) == 1

    def test_a_station_without_coordinates_is_geocoded(self, test_db):
        user_id = _user(test_db)
        leg = _leg()
        leg["arrival"] = _place("Oslo S", "Oslo", lat=None, lon=None, country=None)
        with patch(
            "backend.integrations.photon.client.search_stations",
            return_value=[{"lat": 59.91, "lon": 10.75, "countrycode": "no"}],
        ):
            (seg_id,) = _import_legs(user_id, [leg])
        (seg,) = _rows(test_db, "SELECT * FROM trip_segments WHERE id = ?", seg_id)
        assert (seg["arrival_lat"], seg["arrival_country"]) == (59.91, "NO")


class TestBookings:
    BOOKING = {
        "title": "Vasa Museum",
        "date": "2026-03-14",
        "time": "10:00",
        "place_name": "Vasa Museum",
        "lat": 59.328,
        "lon": 18.091,
        "notes": "Booking 42",
    }

    def test_a_booking_lands_in_the_planner_as_booked(self, test_db):
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id, "Stockholm", start="2026-03-13", end="2026-03-16")

        (item_id,) = _import_bookings(user_id, [self.BOOKING])
        (item,) = _rows(test_db, "SELECT * FROM trip_plan_items WHERE id = ?", item_id)
        assert item["trip_id"] == trip_id
        assert (item["status"], item["date"], item["time"]) == ("booked", "2026-03-14", "10:00")
        assert (item["place_name"], item["notes"]) == ("Vasa Museum", "Booking 42")

    def test_a_booking_never_creates_a_trip(self, test_db):
        user_id = _user(test_db)
        assert _import_bookings(user_id, [self.BOOKING]) == []
        assert _rows(test_db, "SELECT id FROM trips WHERE user_id = ?", user_id) == []

    def test_reading_the_email_again_adds_nothing(self, test_db):
        user_id = _user(test_db)
        _trip(test_db, user_id, "Stockholm", start="2026-03-13", end="2026-03-16")
        assert len(_import_bookings(user_id, [self.BOOKING])) == 1
        assert _import_bookings(user_id, [self.BOOKING]) == []

    def test_the_shortest_covering_trip_wins(self, test_db):
        user_id = _user(test_db)
        _trip(test_db, user_id, "Year abroad", start="2026-01-01", end="2026-12-31")
        weekend = _trip(test_db, user_id, "Weekend", start="2026-03-13", end="2026-03-15")
        (item_id,) = _import_bookings(user_id, [self.BOOKING])
        (item,) = _rows(test_db, "SELECT trip_id FROM trip_plan_items WHERE id = ?", item_id)
        assert item["trip_id"] == weekend


class TestThroughTheSyncPipeline:
    def test_a_train_and_a_concert_in_one_sync(self, test_db):
        """The pipeline imports legs before bookings, so a concert on a train
        journey's day finds the trip that journey just opened."""
        from backend.parsers.email_connector import EmailMessage
        from backend.sync.pipeline import _process_emails

        user_id = _user(test_db)
        email = EmailMessage(
            message_id=f"<{uuid.uuid4()}@sj.se>",
            sender="SJ <noreply@sj.se>",
            subject="Din bokning",
            body="",
            date=datetime(2026, 1, 5, tzinfo=UTC),
        )
        concert = {
            **TestBookings.BOOKING,
            "title": "Concert",
            "date": "2026-03-13",
            "time": "20:00",
        }
        with (
            patch.object(
                kitinerary_import, "extract_kitinerary_ground_legs", return_value=[_leg()]
            ),
            patch.object(kitinerary_import, "extract_kitinerary_bookings", return_value=[concert]),
            patch("backend.sync.pipeline.auto_group_flights", return_value={}),
            patch("backend.sync.pipeline.extract_kitinerary_flights", return_value=[]),
        ):
            result = _process_emails([email], user_id)

        assert (result["segments_created"], result["plan_items_created"]) == (1, 1)
        (item,) = _rows(test_db, "SELECT trip_id, status FROM trip_plan_items")
        (seg,) = _rows(test_db, "SELECT trip_id FROM trip_segments")
        assert item["trip_id"] == seg["trip_id"] and item["status"] == "booked"


class TestStaysAndRentalsFromKitinerary:
    """KDE Itinerary is the last reader in the stays and rentals importers."""

    STAY = {
        "name": "Hotel Example",
        "address": "Rua X 1",
        "city": "Lisbon",
        "country_code": "PT",
        "check_in_datetime": "2026-05-01T15:00",
        "check_out_datetime": "2026-05-03T11:00",
        "booking_reference": "H123",
        "contact": None,
        "price": None,
        "lat": 38.71,
        "lon": -9.14,
    }

    def _email(self, sender="Hotels <noreply@hotel-chain.example>"):
        from backend.parsers.email_connector import EmailMessage

        return EmailMessage(
            message_id=f"<{uuid.uuid4()}@x>", sender=sender, subject="Booking", body="", date=None
        )

    def test_a_kitinerary_stay_is_imported_with_its_own_coordinates(self, test_db):
        from backend.sync import stays_import

        user_id = _user(test_db)
        with (
            patch.object(stays_import, "extract_kitinerary_stays", return_value=[self.STAY]),
            patch("backend.integrations.photon.client.search_places") as geocoder,
        ):
            (stay_id,) = stays_import.import_lodging_from_email(self._email(), user_id)
        geocoder.assert_not_called()
        (stay,) = _rows(test_db, "SELECT * FROM trip_stays WHERE id = ?", stay_id)
        assert (stay["name"], stay["lat"], stay["country"]) == ("Hotel Example", 38.71, "PT")

    def test_our_own_readers_win_over_kitinerary(self, test_db):
        from backend.sync import stays_import

        user_id = _user(test_db)
        own = {**self.STAY, "name": "From the markup", "lat": None, "lon": None}
        with (
            patch.object(stays_import, "extract_lodging_reservations", return_value=[own]),
            patch.object(stays_import, "extract_kitinerary_stays", return_value=[self.STAY]) as kit,
            patch.object(stays_import, "_geocode", return_value=(None, None, None)),
        ):
            stays_import.import_lodging_from_email(self._email(), user_id)
        kit.assert_not_called()
        assert [r["name"] for r in _rows(test_db, "SELECT name FROM trip_stays")] == [
            "From the markup"
        ]

    def test_a_kitinerary_rental_is_imported(self, test_db):
        from backend.sync import car_rentals_import

        user_id = _user(test_db)
        rental = {
            "vendor": "Avis",
            "booking_reference": "546323",
            "pickup_place": "Avis San Diego Airport",
            "pickup_datetime": "2027-08-05T16:00",
            "dropoff_place": "Avis LAX",
            "dropoff_datetime": "2027-08-06T20:00",
            "vehicle": "Honda Civic",
            "driver_name": "John Smith",
        }
        with (
            patch.object(car_rentals_import, "extract_car_rentals", return_value=[]),
            patch.object(car_rentals_import, "extract_kitinerary_rentals", return_value=[rental]),
            patch.object(car_rentals_import, "_geocode", return_value=(32.73, -117.19, "US")),
        ):
            (rental_id,) = car_rentals_import.import_car_rentals_from_email(self._email(), user_id)
        (row,) = _rows(test_db, "SELECT * FROM trip_car_rentals WHERE id = ?", rental_id)
        assert (row["vendor"], row["booking_reference"], row["vehicle"]) == (
            "Avis",
            "546323",
            "Honda Civic",
        )
