"""Tests for backend.boarding_passes.repository (raw CRUD + on-disk image storage)."""

import itertools
import uuid
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


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


def _seed_flight(db_path: str, user_id: int, trip_id: str | None = None) -> str:
    import sqlite3

    flight_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO flights (id, user_id, trip_id, flight_number, departure_airport,
           departure_datetime, arrival_airport, arrival_datetime, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (flight_id, user_id, trip_id, "LA800", "GRU", now, "SCL", now, now, now),
    )
    conn.commit()
    conn.close()
    return flight_id


def _seed_trip(db_path: str, user_id: int) -> str:
    import sqlite3

    trip_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO trips (id, user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (trip_id, user_id, "Test Trip", now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


class TestSave:
    def test_save_writes_file_and_row(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        bp_id = repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name="J DOE",
            seat="12A",
            source_email_id="msg-1",
            source_page=0,
        )

        items = repo.list_for_flight(flight_id)
        assert len(items) == 1
        assert items[0].id == bp_id
        assert items[0].passenger_name == "J DOE"
        assert items[0].seat == "12A"
        assert items[0].image_path is not None
        from pathlib import Path

        assert Path(items[0].image_path).read_bytes() == _PNG_BYTES

    def test_duplicate_source_email_and_page_is_ignored(self, test_db):
        """UNIQUE(source_email_id, source_page) — re-processing the same email is idempotent."""
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name="A",
            seat="1A",
            source_email_id="msg-dup",
            source_page=0,
        )
        repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name="B",
            seat="2B",
            source_email_id="msg-dup",
            source_page=0,
        )

        assert len(repo.list_for_flight(flight_id)) == 1


class TestListForTrip:
    def test_includes_flight_route_info(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        flight_id = _seed_flight(test_db, user_id, trip_id)
        repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name=None,
            seat=None,
            source_email_id=None,
            source_page=0,
        )

        [item] = repo.list_for_trip(trip_id)
        assert item.flight_number == "LA800"
        assert item.departure_airport == "GRU"
        assert item.arrival_airport == "SCL"


class TestAccessQueries:
    def test_can_read_flight_true_for_owner(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)
        assert repo.can_read_flight(flight_id, user_id) is True

    def test_can_read_flight_false_for_stranger(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)
        assert repo.can_read_flight(flight_id, other_id) is False

    def test_flight_owned_by_true_for_owner(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)
        assert repo.flight_owned_by(flight_id, user_id) is True

    def test_get_with_read_access_none_for_stranger(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)
        bp_id = repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name=None,
            seat=None,
            source_email_id=None,
            source_page=0,
        )
        assert repo.get_with_read_access(bp_id, other_id) is None
        assert repo.get_with_read_access(bp_id, owner_id) is not None

    def test_get_owned_none_for_nonowner(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)
        bp_id = repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name=None,
            seat=None,
            source_email_id=None,
            source_page=0,
        )
        assert repo.get_owned(bp_id, other_id) is None
        assert repo.get_owned(bp_id, owner_id) is not None


class TestDelete:
    def test_delete_removes_row(self, test_db):
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)
        bp_id = repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name=None,
            seat=None,
            source_email_id=None,
            source_page=0,
        )

        repo.delete(bp_id)
        assert repo.list_for_flight(flight_id) == []

    def test_delete_image_file_removes_file(self, test_db):
        from pathlib import Path

        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)
        repo.save(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name=None,
            seat=None,
            source_email_id=None,
            source_page=0,
        )
        [item] = repo.list_for_flight(flight_id)
        assert item.image_path is not None
        assert Path(item.image_path).exists()

        repo.delete_image_file(item.image_path)
        assert not Path(item.image_path).exists()


class TestSafeFilePath:
    def test_rejects_path_outside_storage_dir(self, test_db):
        from backend.boarding_passes.errors import AccessDeniedError
        from backend.boarding_passes.repository import BoardingPassRepository

        repo = BoardingPassRepository()
        with pytest.raises(AccessDeniedError):
            repo.safe_file_path("/etc/passwd")
