"""Tests for backend.flights.service (FlightService) — access control and the
create/update/ungroup business logic.

CSV export math lives in test_export_service.py; aircraft lookup lives in
test_aircraft_service.py."""

import itertools
import uuid
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _seed_trip(db_path: str, user_id: int, trip_id: str | None = None, name: str = "Trip") -> str:
    import sqlite3

    trip_id = trip_id or str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trips (id, name, booking_refs, start_date, end_date,
           origin_airport, destination_airport, user_id, created_at, updated_at)
           VALUES (?, ?, '[]', '', '', '', '', ?, ?, ?)""",
        (trip_id, name, user_id, now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


def _create_body(**overrides) -> dict:
    body = {
        "flight_number": "LA800",
        "airline_name": "LATAM",
        "airline_code": "LA",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00",
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00",
        "booking_reference": "",
        "passenger_name": "",
        "seat": "",
        "cabin_class": "",
        "departure_terminal": "",
        "departure_gate": "",
        "arrival_terminal": "",
        "arrival_gate": "",
        "notes": "",
        "trip_id": None,
    }
    body.update(overrides)
    return body


class TestListAndGetAccessControl:
    def test_list_flights_with_inaccessible_trip_raises(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(FlightError) as exc_info:
            service.list_flights(other_id, trip_id, None, 100, 0)
        assert exc_info.value.status_code == 404

    def test_get_flight_not_found_raises(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        with pytest.raises(FlightError) as exc_info:
            service.get_flight("nonexistent", user_id)
        assert exc_info.value.status_code == 404

    def test_get_flight_email_not_found_raises(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        with pytest.raises(FlightError) as exc_info:
            service.get_flight_email("nonexistent", user_id)
        assert exc_info.value.status_code == 404


class TestCreateFlight:
    def test_create_rejects_invalid_flight_number(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        with pytest.raises(FlightError) as exc_info:
            service.create_flight(user_id, _create_body(flight_number="???"))
        assert exc_info.value.status_code == 422

    def test_create_rejects_trip_not_owned(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(FlightError) as exc_info:
            service.create_flight(other_id, _create_body(trip_id=trip_id))
        assert exc_info.value.status_code == 403

    def test_create_recomputes_trip_span(self, test_db):
        from backend.flights.service import FlightService
        from backend.trips.repository import TripRepository

        service = FlightService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        service.create_flight(user_id, _create_body(trip_id=trip_id))

        trip = TripRepository().get_by_id(trip_id)
        assert trip is not None
        assert trip.origin_airport == "GRU"
        assert trip.destination_airport == "LHR"


class TestUpdateFlight:
    def test_update_not_found_raises(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        with pytest.raises(FlightError) as exc_info:
            service.update_flight("nonexistent", user_id, {"seat": "12A"})
        assert exc_info.value.status_code == 404

    def test_update_no_changes_is_noop(self, test_db):
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        flight_id = service.create_flight(user_id, _create_body())

        service.update_flight(flight_id, user_id, dict.fromkeys(_create_body(), None))

        flight = service.get_flight(flight_id, user_id)
        assert flight.flight_number == "LA800"


class TestUngroupFlight:
    def test_ungroup_not_found_raises(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        with pytest.raises(FlightError) as exc_info:
            service.ungroup_flight("nonexistent", user_id)
        assert exc_info.value.status_code == 404

    def test_ungroup_without_trip_raises_400(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        flight_id = service.create_flight(user_id, _create_body(trip_id=None))

        with pytest.raises(FlightError) as exc_info:
            service.ungroup_flight(flight_id, user_id)
        assert exc_info.value.status_code == 400

    def test_ungroup_solo_trip_raises_400(self, test_db):
        from backend.flights.errors import FlightError
        from backend.flights.service import FlightService

        service = FlightService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        flight_id = service.create_flight(user_id, _create_body(trip_id=trip_id))

        with pytest.raises(FlightError) as exc_info:
            service.ungroup_flight(flight_id, user_id)
        assert exc_info.value.status_code == 400

    def test_ungroup_creates_auto_generated_solo_trip(self, test_db):
        from backend.flights.service import FlightService
        from backend.trips.repository import TripRepository

        service = FlightService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        flight_id = service.create_flight(user_id, _create_body(trip_id=trip_id))
        service.create_flight(user_id, _create_body(flight_number="LA801", trip_id=trip_id))

        new_trip_id = service.ungroup_flight(flight_id, user_id)

        new_trip = TripRepository().get_by_id(new_trip_id)
        assert new_trip is not None
        assert new_trip.is_auto_generated == 1
        assert new_trip.origin_airport == "GRU"
        assert new_trip.destination_airport == "LHR"

        moved_flight = service.get_flight(flight_id, user_id)
        assert moved_flight.trip_id == new_trip_id
