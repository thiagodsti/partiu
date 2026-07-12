"""Tests for backend.trips.repository (trips CRUD + bulk enrichment queries)."""

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


def _seed_flight(
    db_path: str,
    user_id: int,
    trip_id: str,
    dep_dt: str,
    arr_dt: str,
    dep_airport: str = "GRU",
    arr_airport: str = "LHR",
    flight_number: str = "LA800",
) -> str:
    import sqlite3

    flight_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO flights (id, user_id, trip_id, flight_number, departure_airport,
           departure_datetime, arrival_airport, arrival_datetime, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            flight_id,
            user_id,
            trip_id,
            flight_number,
            dep_airport,
            dep_dt,
            arr_airport,
            arr_dt,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return flight_id


class TestCreateAndGet:
    def test_create_and_get_by_id(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "My Trip", "[]", "2025-01-01", "2025-01-10", "GRU", "LHR", user_id, "now")

        trip = repo.get_by_id("t1")
        assert trip is not None
        assert trip.name == "My Trip"
        assert trip.user_id == user_id

    def test_get_owned_none_for_other_user(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        repo.create("t1", "My Trip", "[]", "", "", "", "", owner_id, "now")

        assert repo.get_owned("t1", owner_id) is not None
        assert repo.get_owned("t1", other_id) is None


class TestListOwnedAndShared:
    def test_list_owned(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip A", "[]", "2025-01-01", "", "", "", user_id, "now")
        assert len(repo.list_owned(user_id)) == 1

    def test_list_shared_accepted_only(self, test_db):
        import sqlite3

        from backend.trips.repository import TripRepository

        repo = TripRepository()
        owner_id = _seed_user(test_db)
        collab_id = _seed_user(test_db)
        repo.create("t1", "Shared Trip", "[]", "", "", "", "", owner_id, "now")

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)"
            " VALUES ('t1', ?, ?, 'accepted', datetime('now'), datetime('now'))",
            (collab_id, owner_id),
        )
        conn.commit()
        conn.close()

        assert len(repo.list_shared_accepted(collab_id)) == 1
        assert repo.list_shared_accepted(owner_id) == []


class TestUpdateAndDelete:
    def test_update_columns(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Old Name", "[]", "", "", "", "", user_id, "now")

        repo.update("t1", user_id, {"name": "New Name"})
        updated = repo.get_by_id("t1")
        assert updated is not None
        assert updated.name == "New Name"

    def test_delete_owned_removes_trip_and_flights(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        _seed_flight(test_db, user_id, "t1", "2025-01-01T10:00:00", "2025-01-01T12:00:00")

        repo.delete_owned("t1", user_id)
        assert repo.get_by_id("t1") is None
        assert repo.get_flights_for_trip("t1") == []


class TestMerge:
    def test_merge_moves_flights_deletes_source_recomputes_span(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("source", "Source", "[]", "", "", "", "", user_id, "now")
        repo.create("target", "Target", "[]", "", "", "", "", user_id, "now")
        _seed_flight(
            test_db, user_id, "source", "2025-03-01T10:00:00", "2025-03-01T12:00:00", "GRU", "LHR"
        )

        repo.merge_trips("source", "target", user_id, "2025-03-02T00:00:00")

        assert repo.get_by_id("source") is None
        target = repo.get_by_id("target")
        assert target is not None
        assert target.start_date == "2025-03-01"
        assert target.origin_airport == "GRU"
        assert target.destination_airport == "LHR"
        assert len(repo.get_flights_for_trip("target")) == 1


class TestFlightAssignment:
    def test_assign_and_unassign(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        fid = _seed_flight(test_db, user_id, "", "2025-01-01T10:00:00", "2025-01-01T12:00:00")

        assert repo.trip_owned_exists("t1", user_id) is True
        assert repo.flight_owned_exists(fid, user_id) is True

        repo.assign_flight(fid, "t1", user_id, "now")
        assert len(repo.get_flights_for_trip("t1")) == 1

        repo.unassign_flight(fid, "t1", user_id, "now")
        assert repo.get_flights_for_trip("t1") == []


class TestBulkEnrichment:
    def test_get_flight_counts(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        _seed_flight(test_db, user_id, "t1", "2025-01-01T10:00:00", "2025-01-01T12:00:00")
        _seed_flight(test_db, user_id, "t1", "2025-01-02T10:00:00", "2025-01-02T12:00:00")

        assert repo.get_flight_counts(["t1"]) == {"t1": 2}
        assert repo.get_flight_counts([]) == {}

    def test_get_expenses_totals(self, test_db):
        import sqlite3

        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO trip_expenses (id, trip_id, description, amount, currency, created_by, created_at, updated_at)"
            " VALUES (?, 't1', 'Hotel', 100.0, 'EUR', ?, datetime('now'), datetime('now'))",
            (str(uuid.uuid4()), user_id),
        )
        conn.commit()
        conn.close()

        assert repo.get_expenses_totals(["t1"]) == {"t1": {"EUR": 100.0}}

    def test_get_search_index_rows(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        _seed_flight(
            test_db,
            user_id,
            "t1",
            "2025-01-01T10:00:00",
            "2025-01-01T12:00:00",
            dep_airport="GRU",
            arr_airport="LHR",
            flight_number="LA800",
        )

        rows = repo.get_search_index_rows(["t1"])
        assert "t1" in rows
        assert rows["t1"]["dep_iatas"] == "GRU"
        assert rows["t1"]["flight_nums"] == "LA800"


class TestRatingAndNote:
    def test_set_rating(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        repo.set_rating("t1", 4.5, "now")
        trip = repo.get_by_id("t1")
        assert trip is not None
        assert trip.rating == 4.5

    def test_set_note(self, test_db):
        from backend.trips.repository import TripRepository

        repo = TripRepository()
        user_id = _seed_user(test_db)
        repo.create("t1", "Trip", "[]", "", "", "", "", user_id, "now")
        repo.set_note("t1", "Great trip!", "now")
        trip = repo.get_by_id("t1")
        assert trip is not None
        assert trip.note == "Great trip!"
