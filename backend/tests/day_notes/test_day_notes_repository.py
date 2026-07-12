"""Tests for backend.day_notes.repository (raw CRUD for the trip_day_notes table)."""

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


class TestUpsert:
    def test_creates_new_note(self, test_db):
        from backend.day_notes.repository import DayNoteRepository

        repo = DayNoteRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        repo.upsert(trip_id, "2025-06-01", "Museum day", user_id)

        notes = repo.list_for_trip(trip_id)
        assert len(notes) == 1
        assert notes[0].date == "2025-06-01"
        assert notes[0].content == "Museum day"

    def test_upsert_updates_existing_note(self, test_db):
        from backend.day_notes.repository import DayNoteRepository

        repo = DayNoteRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        repo.upsert(trip_id, "2025-06-01", "First version", user_id)
        repo.upsert(trip_id, "2025-06-01", "Second version", user_id)

        notes = repo.list_for_trip(trip_id)
        assert len(notes) == 1
        assert notes[0].content == "Second version"

    def test_updated_by_username_is_joined(self, test_db):
        import sqlite3

        from backend.day_notes.repository import DayNoteRepository

        repo = DayNoteRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        conn = sqlite3.connect(test_db)
        username = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        conn.close()

        repo.upsert(trip_id, "2025-06-01", "Note", user_id)
        [note] = repo.list_for_trip(trip_id)
        assert note.updated_by_username == username


class TestListForTrip:
    def test_orders_by_date_ascending(self, test_db):
        from backend.day_notes.repository import DayNoteRepository

        repo = DayNoteRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        repo.upsert(trip_id, "2025-06-03", "Third", user_id)
        repo.upsert(trip_id, "2025-06-01", "First", user_id)
        repo.upsert(trip_id, "2025-06-02", "Second", user_id)

        notes = repo.list_for_trip(trip_id)
        assert [n.date for n in notes] == ["2025-06-01", "2025-06-02", "2025-06-03"]

    def test_isolates_by_trip(self, test_db):
        from backend.day_notes.repository import DayNoteRepository

        repo = DayNoteRepository()
        user_id = _seed_user(test_db)
        trip1 = _seed_trip(test_db, user_id)
        trip2 = _seed_trip(test_db, user_id)
        repo.upsert(trip1, "2025-06-01", "For trip 1", user_id)

        assert len(repo.list_for_trip(trip1)) == 1
        assert repo.list_for_trip(trip2) == []
