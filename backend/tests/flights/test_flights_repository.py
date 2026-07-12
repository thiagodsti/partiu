"""Tests for backend.flights.repository (FlightRepository)."""

import itertools
import uuid
from datetime import UTC, datetime

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


def _base_fields(**overrides) -> dict:
    fields = {
        "trip_id": None,
        "airline_name": "LATAM",
        "airline_code": "LA",
        "flight_number": "LA800",
        "booking_reference": "ABC123",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00",
        "departure_terminal": None,
        "departure_gate": None,
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00",
        "arrival_terminal": None,
        "arrival_gate": None,
        "passenger_name": None,
        "seat": None,
        "cabin_class": None,
        "duration_minutes": 720,
        "status": "upcoming",
        "departure_timezone": None,
        "arrival_timezone": None,
        "notes": None,
    }
    fields.update(overrides)
    return fields


class TestCreateAndGet:
    def test_create_and_get_by_id(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "2025-01-01T00:00:00")

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.flight_number == "LA800"
        assert flight.user_id == user_id
        assert flight.is_manually_added == 1

    def test_get_by_id_missing_returns_none(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().get_by_id("nope") is None

    def test_get_owned_none_for_other_user(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), owner_id, "now")

        assert repo.get_owned("f1", owner_id) is not None
        assert repo.get_owned("f1", other_id) is None


class TestEmailAndAircraftFields:
    def test_get_email_fields(self, test_db):
        import sqlite3

        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        conn = sqlite3.connect(test_db)
        conn.execute(
            "UPDATE flights SET email_body = ?, email_subject = ?, email_date = ? WHERE id = ?",
            ("<p>hi</p>", "Your flight", "2025-01-01", "f1"),
        )
        conn.commit()
        conn.close()

        row = repo.get_email_fields("f1")
        assert row is not None
        assert row["email_body"] == "<p>hi</p>"
        assert row["email_subject"] == "Your flight"

    def test_get_email_fields_missing_returns_none(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().get_email_fields("nope") is None

    def test_get_aircraft_fields(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        row = repo.get_aircraft_fields("f1")
        assert row is not None
        assert row["flight_number"] == "LA800"
        assert row["aircraft_fetched_at"] is None

    def test_update_aircraft_recovery(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.update_aircraft_recovery("f1", user_id, "Boeing 787", "PR-XYZ", "2025-01-02T00:00:00")

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.aircraft_type == "Boeing 787"
        assert flight.aircraft_registration == "PR-XYZ"


class TestCountInTrip:
    def test_count_in_trip(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        assert repo.count_in_trip(trip_id) == 0

        repo.create("f1", _base_fields(trip_id=trip_id), user_id, "now")
        repo.create("f2", _base_fields(trip_id=trip_id, flight_number="LA801"), user_id, "now")
        assert repo.count_in_trip(trip_id) == 2


class TestListFlights:
    def test_list_by_trip_id(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        other_trip_id = _seed_trip(test_db, user_id, name="Other")
        repo.create("f1", _base_fields(trip_id=trip_id), user_id, "now")
        repo.create(
            "f2", _base_fields(trip_id=other_trip_id, flight_number="LA801"), user_id, "now"
        )

        flights, total = repo.list_flights(user_id, trip_id, None, 100, 0)
        assert total == 1
        assert flights[0].id == "f1"

    def test_list_by_status_filter(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(status="completed"), user_id, "now")
        repo.create("f2", _base_fields(flight_number="LA801", status="upcoming"), user_id, "now")

        flights, total = repo.list_flights(user_id, None, "completed", 100, 0)
        assert total == 1
        assert flights[0].id == "f1"

    def test_list_no_trip_id_includes_shared(self, test_db):
        import sqlite3

        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        owner_id = _seed_user(test_db)
        collaborator_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create("f1", _base_fields(trip_id=trip_id), owner_id, "now")

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO trip_shares (trip_id, user_id, status, invited_by) VALUES (?, ?, 'accepted', ?)",
            (trip_id, collaborator_id, owner_id),
        )
        conn.commit()
        conn.close()

        flights, total = repo.list_flights(collaborator_id, None, None, 100, 0)
        assert total == 1
        assert flights[0].id == "f1"

    def test_list_pagination(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        for i in range(5):
            repo.create(f"f{i}", _base_fields(flight_number=f"LA{i:04d}"), user_id, "now")

        flights, total = repo.list_flights(user_id, None, None, 2, 0)
        assert total == 5
        assert len(flights) == 2


class TestUpdateAndDelete:
    def test_update(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.update("f1", user_id, {"seat": "12A", "updated_at": "later"})

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.seat == "12A"

    def test_delete_owned(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.delete_owned("f1", user_id)

        assert repo.get_by_id("f1") is None

    def test_delete_owned_wrong_user_noop(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), owner_id, "now")

        repo.delete_owned("f1", other_id)

        assert repo.get_by_id("f1") is not None


class TestFindByNumberAndDate:
    def test_no_match_returns_none(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().find_by_number_and_date("LA1234", "2025-06-01", 1) is None

    def test_finds_by_number_and_date(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create(
            "f1",
            _base_fields(flight_number="LA1234", departure_datetime="2025-06-01T10:00:00"),
            user_id,
            "now",
        )
        repo.update("f1", user_id, {"is_manually_added": 0})

        found = repo.find_by_number_and_date("LA1234", "2025-06-01", user_id)
        assert found is not None
        assert found.id == "f1"

    def test_manual_flight_not_found(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create(
            "f1",
            _base_fields(flight_number="LA1234", departure_datetime="2025-06-01T10:00:00"),
            user_id,
            "now",
        )

        assert repo.find_by_number_and_date("LA1234", "2025-06-01", user_id) is None


class TestFindLatestByNumber:
    def test_no_match_returns_none(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().find_latest_by_number("LA1234", 1) is None

    def test_finds_by_number_regardless_of_manual_flag(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(flight_number="LA1234"), user_id, "now")

        found = repo.find_latest_by_number("LA1234", user_id)
        assert found is not None
        assert found.id == "f1"

    def test_returns_most_recent_departure(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create(
            "old",
            _base_fields(flight_number="LA1234", departure_datetime="2024-01-01T10:00:00"),
            user_id,
            "now",
        )
        repo.create(
            "new",
            _base_fields(flight_number="LA1234", departure_datetime="2025-06-01T10:00:00"),
            user_id,
            "now",
        )

        found = repo.find_latest_by_number("LA1234", user_id)
        assert found is not None
        assert found.id == "new"

    def test_isolates_by_user(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        repo.create("f1", _base_fields(flight_number="LA1234"), owner_id, "now")

        assert repo.find_latest_by_number("LA1234", other_id) is None


class TestListMissingAircraftData:
    def test_empty_when_no_flights(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().list_missing_aircraft_data(1) == []

    def test_includes_flights_without_aircraft_fetch(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        assert repo.list_missing_aircraft_data(user_id) == ["f1"]

    def test_excludes_flights_already_fetched(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        repo.update("f1", user_id, {"aircraft_fetched_at": "2025-01-02T00:00:00"})

        assert repo.list_missing_aircraft_data(user_id) == []

    def test_respects_limit(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        for i in range(3):
            repo.create(f"f{i}", _base_fields(flight_number=f"LA{i:04d}"), user_id, "now")

        assert len(repo.list_missing_aircraft_data(user_id, limit=2)) == 2

    def test_isolates_by_user(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), owner_id, "now")

        assert repo.list_missing_aircraft_data(other_id) == []


class TestAircraftFetchAttempts:
    def test_zero_by_default(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        assert repo.get_aircraft_fetch_attempts("f1") == 0

    def test_unknown_flight_returns_zero(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().get_aircraft_fetch_attempts("nope") == 0

    def test_reflects_scheduled_retries(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.schedule_aircraft_retry("f1", "2025-06-01T12:00:00", "now")
        repo.schedule_aircraft_retry("f1", "2025-06-01T13:00:00", "now")

        assert repo.get_aircraft_fetch_attempts("f1") == 2


class TestListMissingAircraftNames:
    def test_empty_when_no_flights(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().list_missing_aircraft_names() == []

    def test_includes_flight_with_icao_but_no_type(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        repo.update("f1", user_id, {"aircraft_icao": "ABC123", "aircraft_type": ""})

        rows = repo.list_missing_aircraft_names()
        assert [r["id"] for r in rows] == ["f1"]
        assert rows[0]["aircraft_icao"] == "ABC123"

    def test_excludes_flight_with_both_fields_populated(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        repo.update(
            "f1",
            user_id,
            {
                "aircraft_icao": "ABC123",
                "aircraft_type": "Boeing 777",
                "aircraft_registration": "PP-XYZ",
            },
        )

        assert repo.list_missing_aircraft_names() == []

    def test_excludes_flight_without_icao(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        assert repo.list_missing_aircraft_names() == []


class TestListNeedingAircraftFetch:
    def test_finds_flight_in_window_without_fetch(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")

        rows = repo.list_needing_aircraft_fetch("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert [r["id"] for r in rows] == ["f1"]

    def test_excludes_flight_outside_window(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-01-01T12:00:00"), user_id, "now")

        rows = repo.list_needing_aircraft_fetch("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert rows == []

    def test_excludes_cancelled_flight(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create(
            "f1",
            _base_fields(departure_datetime="2025-06-01T12:00:00", status="cancelled"),
            user_id,
            "now",
        )

        rows = repo.list_needing_aircraft_fetch("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert rows == []

    def test_excludes_flight_already_fetched(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")
        repo.update("f1", user_id, {"aircraft_fetched_at": "2025-06-01T00:00:00"})

        rows = repo.list_needing_aircraft_fetch("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert rows == []

    def test_excludes_flight_in_backoff(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")
        repo.update("f1", user_id, {"aircraft_next_retry_at": "2025-06-02T00:00:00"})

        rows = repo.list_needing_aircraft_fetch("2025-06-01T00:00:00", "2025-06-01T18:00:00")
        assert rows == []

    def test_includes_flight_past_backoff(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")
        repo.update("f1", user_id, {"aircraft_next_retry_at": "2025-06-01T00:00:00"})

        rows = repo.list_needing_aircraft_fetch("2025-06-01T00:00:00", "2025-06-01T18:00:00")
        assert [r["id"] for r in rows] == ["f1"]


class TestListNeedingAircraftRefresh:
    def test_finds_unconfirmed_fetched_flight_in_window(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")
        repo.update("f1", user_id, {"aircraft_fetched_at": "2025-05-30T00:00:00"})

        rows = repo.list_needing_aircraft_refresh("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert [r["id"] for r in rows] == ["f1"]

    def test_excludes_confirmed_flight(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")
        repo.update(
            "f1",
            user_id,
            {"aircraft_fetched_at": "2025-05-30T00:00:00", "aircraft_confirmed": 1},
        )

        rows = repo.list_needing_aircraft_refresh("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert rows == []

    def test_excludes_never_fetched_flight(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(departure_datetime="2025-06-01T12:00:00"), user_id, "now")

        rows = repo.list_needing_aircraft_refresh("2025-06-01T00:00:00", "2025-06-02T00:00:00")
        assert rows == []


class TestListEligibleForImmediateFetch:
    def test_empty_flight_ids_returns_empty(self, test_db):
        from backend.flights.repository import FlightRepository

        assert FlightRepository().list_eligible_for_immediate_fetch([], "now") == []

    def test_includes_eligible_flight(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        rows = repo.list_eligible_for_immediate_fetch(["f1"], "2025-06-01T00:00:00")
        assert [r["id"] for r in rows] == ["f1"]

    def test_excludes_id_not_requested(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        repo.create("f2", _base_fields(flight_number="LA801"), user_id, "now")

        rows = repo.list_eligible_for_immediate_fetch(["f1"], "2025-06-01T00:00:00")
        assert [r["id"] for r in rows] == ["f1"]

    def test_excludes_already_fetched(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        repo.update("f1", user_id, {"aircraft_fetched_at": "2025-06-01T00:00:00"})

        rows = repo.list_eligible_for_immediate_fetch(["f1"], "2025-06-01T00:00:00")
        assert rows == []


class TestRecoverAircraftName:
    def test_updates_type_and_registration(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.recover_aircraft_name("f1", "Boeing 777-300ER", "PP-XYZ", "later")

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.aircraft_type == "Boeing 777-300ER"
        assert flight.aircraft_registration == "PP-XYZ"
        assert flight.updated_at == "later"


class TestMarkAircraftFetchGivenUp:
    def test_sets_fetched_at(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.mark_aircraft_fetch_given_up("f1", "2025-06-01T00:00:00")

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.aircraft_fetched_at == "2025-06-01T00:00:00"


class TestUpdateAircraftFetchResult:
    def test_sets_all_fields_and_clears_retry_state(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")
        repo.schedule_aircraft_retry("f1", "2025-06-01T12:00:00", "now")
        assert repo.get_aircraft_fetch_attempts("f1") == 1

        repo.update_aircraft_fetch_result(
            "f1", "Boeing 777-300ER", "ABC123", "PP-XYZ", True, "2025-06-01T00:00:00"
        )

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.aircraft_type == "Boeing 777-300ER"
        assert flight.aircraft_icao == "ABC123"
        assert flight.aircraft_registration == "PP-XYZ"
        assert flight.aircraft_confirmed == 1
        assert flight.aircraft_fetched_at == "2025-06-01T00:00:00"
        assert repo.get_aircraft_fetch_attempts("f1") == 0

    def test_unconfirmed_stores_zero(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.update_aircraft_fetch_result(
            "f1", "Boeing 777", "ABC123", "PP-XYZ", False, "2025-06-01T00:00:00"
        )

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.aircraft_confirmed == 0


class TestScheduleAircraftRetry:
    def test_increments_attempts_and_sets_retry_time(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(), user_id, "now")

        repo.schedule_aircraft_retry("f1", "2025-06-01T12:00:00", "2025-06-01T00:00:00")

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.aircraft_next_retry_at == "2025-06-01T12:00:00"
        assert flight.aircraft_fetch_attempts == 1
        assert flight.updated_at == "2025-06-01T00:00:00"


def _synced_fields(**overrides) -> dict:
    fields = {
        "airline_name": "LATAM",
        "airline_code": "LA",
        "flight_number": "LA800",
        "booking_reference": "ABC123",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00+00:00",
        "departure_terminal": "",
        "departure_gate": "",
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00+00:00",
        "arrival_terminal": "",
        "arrival_gate": "",
        "passenger_name": "",
        "seat": "",
        "cabin_class": "",
        "duration_minutes": 720,
        "status": "upcoming",
        "departure_timezone": None,
        "arrival_timezone": None,
        "email_message_id": "<msg@test.com>:LA800",
        "email_subject": "Your flight",
        "email_date": "2025-05-01T00:00:00+00:00",
        "email_body": "<p>hi</p>",
    }
    fields.update(overrides)
    return fields


class TestCreateSynced:
    def test_insert_new_flight(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)

        rowcount = repo.create_synced("f1", _synced_fields(), user_id, "now")
        assert rowcount == 1

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.flight_number == "LA800"
        assert flight.is_manually_added == 0
        assert flight.email_message_id == "<msg@test.com>:LA800"

    def test_duplicate_message_id_ignored(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)

        repo.create_synced("f1", _synced_fields(), user_id, "now")
        rowcount = repo.create_synced("f2", _synced_fields(), user_id, "now")

        assert rowcount == 0
        assert repo.get_by_id("f2") is None


class TestUpdateSynced:
    def test_updates_fields(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create_synced("f1", _synced_fields(), user_id, "now")

        repo.update_synced("f1", _synced_fields(seat="22A"), "later")

        flight = repo.get_by_id("f1")
        assert flight is not None
        assert flight.seat == "22A"
        assert flight.updated_at == "later"


class TestListForExport:
    def test_list_for_export_only_completed(self, test_db):
        from backend.flights.repository import FlightRepository

        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create("f1", _base_fields(status="completed"), user_id, "now")
        repo.create("f2", _base_fields(flight_number="LA801", status="upcoming"), user_id, "now")

        rows = repo.list_for_export(user_id)
        assert len(rows) == 1
        assert rows[0]["flight_number"] == "LA800"
