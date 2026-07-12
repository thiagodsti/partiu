"""Tests for backend.packing.service (trip-access checks + validation rules)."""

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


class TestListItems:
    def test_raises_when_no_access(self, test_db):
        from backend.packing.service import PackingService, TripAccessError

        service = PackingService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_items(trip_id, other_id)

    def test_returns_items_for_owner(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        service.create_item(trip_id, user_id, "Item")

        assert len(service.list_items(trip_id, user_id)) == 1


class TestCreateItem:
    def test_rejects_blank_text(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_item(trip_id, user_id, "   ")

    def test_strips_text(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        item_id = service.create_item(trip_id, user_id, "  Toothbrush  ")
        [item] = service.list_items(trip_id, user_id)
        assert item.id == item_id
        assert item.text == "Toothbrush"

    def test_raises_when_no_access(self, test_db):
        from backend.packing.service import PackingService, TripAccessError

        service = PackingService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.create_item(trip_id, other_id, "Item")


class TestUpdateItem:
    def test_raises_when_item_missing(self, test_db):
        from backend.packing.service import PackingItemNotFoundError, PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(PackingItemNotFoundError):
            service.update_item(trip_id, "nonexistent-id", user_id, checked=True)

    def test_rejects_blank_text(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = service.create_item(trip_id, user_id, "Shoes")

        with pytest.raises(ValueError):
            service.update_item(trip_id, item_id, user_id, text="   ")

    def test_updates_checked(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = service.create_item(trip_id, user_id, "Sunscreen")

        service.update_item(trip_id, item_id, user_id, checked=True)
        [item] = service.list_items(trip_id, user_id)
        assert item.checked is True


class TestDeleteItem:
    def test_raises_when_item_missing(self, test_db):
        from backend.packing.service import PackingItemNotFoundError, PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(PackingItemNotFoundError):
            service.delete_item(trip_id, "nonexistent-id", user_id)

    def test_deletes_existing_item(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        item_id = service.create_item(trip_id, user_id, "Camera")

        service.delete_item(trip_id, item_id, user_id)
        assert service.list_items(trip_id, user_id) == []


class TestClearChecked:
    def test_raises_when_no_access(self, test_db):
        from backend.packing.service import PackingService, TripAccessError

        service = PackingService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.clear_checked(trip_id, other_id)

    def test_removes_only_checked(self, test_db):
        from backend.packing.service import PackingService

        service = PackingService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        unchecked_id = service.create_item(trip_id, user_id, "Unchecked")
        checked_id = service.create_item(trip_id, user_id, "Checked")
        service.update_item(trip_id, checked_id, user_id, checked=True)

        service.clear_checked(trip_id, user_id)

        remaining = service.list_items(trip_id, user_id)
        assert len(remaining) == 1
        assert remaining[0].id == unchecked_id
