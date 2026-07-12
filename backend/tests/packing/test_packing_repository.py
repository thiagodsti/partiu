"""Tests for backend.packing.repository (raw CRUD for the packing_items table)."""

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


class TestCreate:
    def test_create_and_list(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = str(uuid.uuid4())

        repo.create(item_id, trip_id, "Toothbrush", user_id)

        items = repo.list_for_trip(trip_id)
        assert len(items) == 1
        assert items[0].id == item_id
        assert items[0].text == "Toothbrush"
        assert items[0].checked is False
        assert items[0].created_by == user_id

    def test_sort_order_increments(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        for text in ("A", "B", "C"):
            repo.create(str(uuid.uuid4()), trip_id, text, user_id)

        items = repo.list_for_trip(trip_id)
        assert [i.sort_order for i in items] == [0, 1, 2]

    def test_isolates_by_trip(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip1 = _seed_trip(test_db, user_id)
        trip2 = _seed_trip(test_db, user_id)
        repo.create(str(uuid.uuid4()), trip1, "For trip 1", user_id)

        assert len(repo.list_for_trip(trip1)) == 1
        assert repo.list_for_trip(trip2) == []


class TestGet:
    def test_get_existing(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = str(uuid.uuid4())
        repo.create(item_id, trip_id, "Passport", user_id)

        item = repo.get(item_id, trip_id)
        assert item is not None
        assert item.text == "Passport"

    def test_get_nonexistent_returns_none(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        assert repo.get("nonexistent-id", trip_id) is None


class TestUpdate:
    def test_update_text(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = str(uuid.uuid4())
        repo.create(item_id, trip_id, "Old name", user_id)

        repo.update(item_id, trip_id, {"text": "New name"})
        item = repo.get(item_id, trip_id)
        assert item is not None
        assert item.text == "New name"

    def test_update_checked(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = str(uuid.uuid4())
        repo.create(item_id, trip_id, "Sunscreen", user_id)

        repo.update(item_id, trip_id, {"checked": 1})
        item = repo.get(item_id, trip_id)
        assert item is not None
        assert item.checked is True


class TestDelete:
    def test_delete_removes_item(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = str(uuid.uuid4())
        repo.create(item_id, trip_id, "Camera", user_id)

        repo.delete(item_id, trip_id)
        assert repo.get(item_id, trip_id) is None


class TestClearChecked:
    def test_removes_only_checked_items(self, test_db):
        from backend.packing.repository import PackingRepository

        repo = PackingRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        unchecked_id = str(uuid.uuid4())
        checked_id = str(uuid.uuid4())
        repo.create(unchecked_id, trip_id, "Unchecked", user_id)
        repo.create(checked_id, trip_id, "Checked", user_id)
        repo.update(checked_id, trip_id, {"checked": 1})

        repo.clear_checked(trip_id)

        remaining = repo.list_for_trip(trip_id)
        assert len(remaining) == 1
        assert remaining[0].id == unchecked_id
