"""Tests for backend.day_notes.service (trip-access checks + date-format validation)."""

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


class TestListNotes:
    def test_raises_when_no_access(self, test_db):
        from backend.day_notes.service import DayNoteService, TripAccessError

        service = DayNoteService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_notes(trip_id, other_id)

    def test_returns_notes_for_owner(self, test_db):
        from backend.day_notes.service import DayNoteService

        service = DayNoteService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        service.upsert_note(trip_id, "2025-06-01", "Note", user_id)

        assert len(service.list_notes(trip_id, user_id)) == 1


class TestUpsertNote:
    def test_rejects_invalid_date_format(self, test_db):
        from backend.day_notes.service import DayNoteService, InvalidDateError

        service = DayNoteService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(InvalidDateError):
            service.upsert_note(trip_id, "not-a-date", "Note", user_id)

    def test_validation_runs_before_access_check(self, test_db):
        """A malformed date on someone else's trip should 422 (InvalidDateError), not
        404 (TripAccessError) — matches the original route's ordering."""
        from backend.day_notes.service import DayNoteService, InvalidDateError

        service = DayNoteService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(InvalidDateError):
            service.upsert_note(trip_id, "bad-date", "Note", other_id)

    def test_raises_access_error_when_date_valid(self, test_db):
        from backend.day_notes.service import DayNoteService, TripAccessError

        service = DayNoteService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.upsert_note(trip_id, "2025-06-01", "Note", other_id)

    def test_creates_and_updates_note(self, test_db):
        from backend.day_notes.service import DayNoteService

        service = DayNoteService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        service.upsert_note(trip_id, "2025-06-01", "First", user_id)
        service.upsert_note(trip_id, "2025-06-01", "Second", user_id)

        [note] = service.list_notes(trip_id, user_id)
        assert note.content == "Second"
