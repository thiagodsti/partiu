"""Tests for backend.boarding_passes.service (access checks + upload validation rules)."""

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


class TestListForTrip:
    def test_raises_when_no_access(self, test_db):
        from backend.boarding_passes.service import BoardingPassService, TripAccessError

        service = BoardingPassService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_for_trip(trip_id, other_id)


class TestListForFlight:
    def test_raises_when_no_access(self, test_db):
        from backend.boarding_passes.service import BoardingPassService, FlightAccessError

        service = BoardingPassService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)

        with pytest.raises(FlightAccessError):
            service.list_for_flight(flight_id, other_id)


class TestUploadFlow:
    def test_check_upload_allowed_rejects_nonowner(self, test_db):
        from backend.boarding_passes.service import BoardingPassService, FlightAccessError

        service = BoardingPassService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)

        with pytest.raises(FlightAccessError):
            service.check_upload_allowed(flight_id, other_id, "image/png")

    def test_check_upload_allowed_rejects_bad_content_type(self, test_db):
        from backend.boarding_passes.service import BoardingPassService, UnsupportedFileTypeError

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        with pytest.raises(UnsupportedFileTypeError):
            service.check_upload_allowed(flight_id, user_id, "application/pdf")

    def test_check_upload_allowed_passes_for_owner_and_png(self, test_db):
        from backend.boarding_passes.service import BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        service.check_upload_allowed(flight_id, user_id, "image/png")  # should not raise

    def test_save_upload_rejects_too_small(self, test_db):
        from backend.boarding_passes.service import BoardingPassService, FileTooSmallError

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        with pytest.raises(FileTooSmallError):
            service.save_upload(flight_id, b"x")

    def test_save_upload_rejects_too_large(self, test_db):
        from backend.boarding_passes.service import BoardingPassService, FileTooLargeError

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        with pytest.raises(FileTooLargeError):
            service.save_upload(flight_id, b"x" * (10 * 1024 * 1024 + 1))

    def test_save_upload_succeeds(self, test_db):
        from backend.boarding_passes.service import BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        bp_id = service.save_upload(flight_id, _PNG_BYTES)
        items = service.list_for_flight(flight_id, user_id)
        assert len(items) == 1
        assert items[0].id == bp_id


class TestSaveFromSync:
    def test_saves_without_access_check(self, test_db):
        """sync/pipeline.py already scoped the flight lookup to the user — no re-check here."""
        from backend.boarding_passes.service import BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)

        bp_id = service.save_from_sync(
            flight_id=flight_id,
            image_bytes=_PNG_BYTES,
            passenger_name="J DOE",
            seat="12A",
            source_email_id="msg-1",
            source_page=0,
        )
        items = service.list_for_flight(flight_id, user_id)
        assert items[0].id == bp_id
        assert items[0].passenger_name == "J DOE"


class TestGetImagePath:
    def test_raises_not_found_for_unknown_id(self, test_db):
        from backend.boarding_passes.service import BoardingPassNotFoundError, BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        with pytest.raises(BoardingPassNotFoundError):
            service.get_image_path("nonexistent-id", user_id)

    def test_raises_not_found_when_no_access(self, test_db):
        from backend.boarding_passes.service import BoardingPassNotFoundError, BoardingPassService

        service = BoardingPassService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)
        bp_id = service.save_upload(flight_id, _PNG_BYTES)

        with pytest.raises(BoardingPassNotFoundError):
            service.get_image_path(bp_id, other_id)

    def test_returns_path_for_owner(self, test_db):
        from pathlib import Path

        from backend.boarding_passes.service import BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)
        bp_id = service.save_upload(flight_id, _PNG_BYTES)

        path = service.get_image_path(bp_id, user_id)
        assert isinstance(path, Path)
        assert path.exists()


class TestDelete:
    def test_raises_not_found_for_unknown_id(self, test_db):
        from backend.boarding_passes.service import BoardingPassNotFoundError, BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        with pytest.raises(BoardingPassNotFoundError):
            service.delete("nonexistent-id", user_id)

    def test_raises_not_found_when_not_owner(self, test_db):
        from backend.boarding_passes.service import BoardingPassNotFoundError, BoardingPassService

        service = BoardingPassService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, owner_id)
        bp_id = service.save_upload(flight_id, _PNG_BYTES)

        with pytest.raises(BoardingPassNotFoundError):
            service.delete(bp_id, other_id)

    def test_deletes_row_and_image_file(self, test_db):
        from pathlib import Path

        from backend.boarding_passes.service import BoardingPassService

        service = BoardingPassService()
        user_id = _seed_user(test_db)
        flight_id = _seed_flight(test_db, user_id)
        bp_id = service.save_upload(flight_id, _PNG_BYTES)
        image_path = service.get_image_path(bp_id, user_id)

        service.delete(bp_id, user_id)
        assert service.list_for_flight(flight_id, user_id) == []
        assert not Path(image_path).exists()
