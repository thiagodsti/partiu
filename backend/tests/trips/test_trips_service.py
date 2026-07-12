"""Tests for backend.trips.service (merge, rating, note, list assembly — the
endpoints that had no test coverage at all before this refactor)."""

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


def _get_trip(trip_id: str):
    from backend.trips.repository import TripRepository

    trip = TripRepository().get_by_id(trip_id)
    assert trip is not None
    return trip


def _seed_share(db_path: str, trip_id: str, user_id: int, status: str = "accepted") -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
        (trip_id, user_id, user_id, status),
    )
    conn.commit()
    conn.close()


class TestMergeTrip:
    def test_rejects_self_merge(self, test_db):
        from backend.trips.service import TripError, TripService

        service = TripService()
        user_id = _seed_user(test_db)
        trip_id = service.create_trip(user_id, "Trip", [], "", "", "", "")

        with pytest.raises(TripError) as exc_info:
            service.merge_trip(trip_id, trip_id, user_id)
        assert exc_info.value.status_code == 400

    def test_rejects_when_source_not_owned(self, test_db):
        from backend.trips.service import TripError, TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        source_id = service.create_trip(owner_id, "Source", [], "", "", "", "")
        target_id = service.create_trip(other_id, "Target", [], "", "", "", "")

        with pytest.raises(TripError) as exc_info:
            service.merge_trip(source_id, target_id, other_id)
        assert exc_info.value.status_code == 404

    def test_rejects_when_target_not_accessible(self, test_db):
        from backend.trips.service import TripError, TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        source_id = service.create_trip(owner_id, "Source", [], "", "", "", "")
        target_id = service.create_trip(other_id, "Target", [], "", "", "", "")

        with pytest.raises(TripError) as exc_info:
            service.merge_trip(source_id, target_id, owner_id)
        assert exc_info.value.status_code == 404
        assert "Target trip not found" in str(exc_info.value)

    def test_successful_merge_deletes_source(self, test_db):
        from backend.trips.repository import TripRepository
        from backend.trips.service import TripService

        service = TripService()
        user_id = _seed_user(test_db)
        source_id = service.create_trip(user_id, "Source", [], "", "", "", "")
        target_id = service.create_trip(user_id, "Target", [], "", "", "", "")

        service.merge_trip(source_id, target_id, user_id)

        repo = TripRepository()
        assert repo.get_by_id(source_id) is None
        assert repo.get_by_id(target_id) is not None


class TestSetRating:
    def test_rejects_invalid_rating(self, test_db):
        from backend.trips.service import TripError, TripService

        service = TripService()
        user_id = _seed_user(test_db)
        trip_id = service.create_trip(user_id, "Trip", [], "", "", "", "")

        with pytest.raises(TripError) as exc_info:
            service.set_rating(trip_id, user_id, 0.3)
        assert exc_info.value.status_code == 422

    def test_accepts_valid_half_step_rating(self, test_db):
        from backend.trips.repository import TripRepository
        from backend.trips.service import TripService

        service = TripService()
        user_id = _seed_user(test_db)
        trip_id = service.create_trip(user_id, "Trip", [], "", "", "", "")

        service.set_rating(trip_id, user_id, 4.5)
        assert _get_trip(trip_id).rating == 4.5

    def test_clears_rating_with_none(self, test_db):
        from backend.trips.repository import TripRepository
        from backend.trips.service import TripService

        service = TripService()
        user_id = _seed_user(test_db)
        trip_id = service.create_trip(user_id, "Trip", [], "", "", "", "")
        service.set_rating(trip_id, user_id, 4.5)

        service.set_rating(trip_id, user_id, None)
        assert _get_trip(trip_id).rating is None

    def test_collaborator_can_set_rating(self, test_db):
        from backend.trips.repository import TripRepository
        from backend.trips.service import TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        collab_id = _seed_user(test_db)
        trip_id = service.create_trip(owner_id, "Trip", [], "", "", "", "")
        _seed_share(test_db, trip_id, collab_id)

        service.set_rating(trip_id, collab_id, 3.0)
        assert _get_trip(trip_id).rating == 3.0

    def test_rejects_when_no_access(self, test_db):
        from backend.trips.service import TripError, TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = service.create_trip(owner_id, "Trip", [], "", "", "", "")

        with pytest.raises(TripError):
            service.set_rating(trip_id, other_id, 3.0)


class TestSetNote:
    def test_collaborator_can_set_note(self, test_db):
        from backend.trips.repository import TripRepository
        from backend.trips.service import TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        collab_id = _seed_user(test_db)
        trip_id = service.create_trip(owner_id, "Trip", [], "", "", "", "")
        _seed_share(test_db, trip_id, collab_id)

        service.set_note(trip_id, collab_id, "Great trip")
        assert _get_trip(trip_id).note == "Great trip"

    def test_rejects_when_no_access(self, test_db):
        from backend.trips.service import TripError, TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = service.create_trip(owner_id, "Trip", [], "", "", "", "")

        with pytest.raises(TripError):
            service.set_note(trip_id, other_id, "sneaky")


class TestListTrips:
    def test_search_index_includes_name_and_flight_data(self, test_db):
        import sqlite3

        from backend.trips.service import TripService

        service = TripService()
        user_id = _seed_user(test_db)
        trip_id = service.create_trip(user_id, "Résumé Trip", [], "", "", "", "")
        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(test_db)
        conn.execute(
            """INSERT INTO flights (id, user_id, trip_id, flight_number, departure_airport,
               departure_datetime, arrival_airport, arrival_datetime, created_at, updated_at)
               VALUES (?, ?, ?, 'LA800', 'GRU', ?, 'LHR', ?, ?, ?)""",
            (str(uuid.uuid4()), user_id, trip_id, now, now, now, now),
        )
        conn.commit()
        conn.close()

        [item] = service.list_trips(user_id)
        # Accent-insensitive + lowercase
        assert "resume" in item.search_index
        assert "gru" in item.search_index
        assert "la800" in item.search_index

    def test_shared_trip_shows_owner_username_and_not_owner(self, test_db):
        from backend.trips.service import TripService

        service = TripService()
        owner_id = _seed_user(test_db)
        collab_id = _seed_user(test_db)
        trip_id = service.create_trip(owner_id, "Trip", [], "", "", "", "")
        _seed_share(test_db, trip_id, collab_id)

        [item] = service.list_trips(collab_id)
        assert item.is_owner is False
        assert item.owner_username is not None

    def test_owned_trip_has_no_owner_username(self, test_db):
        from backend.trips.service import TripService

        service = TripService()
        user_id = _seed_user(test_db)
        service.create_trip(user_id, "Trip", [], "", "", "", "")

        [item] = service.list_trips(user_id)
        assert item.is_owner is True
        assert item.owner_username is None
