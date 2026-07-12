"""Tests for backend.expenses.guests_service (ownership checks + trip-scoped picker)."""

import uuid
from datetime import UTC, datetime

import pytest

from backend.tests.expenses.conftest import _seed_trip, _seed_user


class TestCreate:
    def test_rejects_blank_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)

        with pytest.raises(ValueError):
            service.create(owner_id, "   ")

    def test_strips_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)

        service.create(owner_id, "  Grandma  ")
        [guest] = service.list_mine(owner_id)
        assert guest.name == "Grandma"


class TestListForTrip:
    def test_raises_when_no_access(self, test_db):
        from backend.expenses.errors import TripAccessError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_for_trip(trip_id, other_id)

    def test_only_returns_trip_referenced_guests_not_unused_ones(self, test_db):
        """Guests are scoped per trip: a guest owned by the caller but never used
        on this trip must not show up, even though a guest actually tagged on
        this trip (owned by someone else entirely) does."""
        import sqlite3

        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        service.create(owner_id, "Own unused guest")

        other_owner = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO guests (owner_id, name, created_at) VALUES (?, ?, ?)",
            (other_owner, "Trip-tagged guest", datetime.now(UTC).isoformat()),
        )
        conn.commit()
        other_guest_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by,
                    paid_by_guest_id, created_at, updated_at)
               VALUES (?, ?, 'Cab', 30.0, 'EUR', ?, ?, ?, ?)""",
            (str(uuid.uuid4()), trip_id, owner_id, other_guest_id, now, now),
        )
        conn.commit()
        conn.close()

        guests = service.list_for_trip(trip_id, owner_id)
        ids = {g.id for g in guests}
        assert ids == {other_guest_id}


class TestRename:
    def test_rejects_blank_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")

        with pytest.raises(ValueError):
            service.rename(guest_id, owner_id, "   ")

    def test_raises_when_not_owner(self, test_db):
        from backend.expenses.errors import GuestNotFoundError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")

        with pytest.raises(GuestNotFoundError):
            service.rename(guest_id, other_id, "Grandpa")

    def test_renames_and_strips_name(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")

        updated = service.rename(guest_id, owner_id, "  Grandpa  ")
        assert updated.name == "Grandpa"
        [guest] = service.list_mine(owner_id)
        assert guest.name == "Grandpa"


class TestDelete:
    def test_raises_when_not_owner(self, test_db):
        from backend.expenses.errors import GuestNotFoundError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")

        with pytest.raises(GuestNotFoundError):
            service.delete(guest_id, other_id)

    def test_raises_when_in_use(self, test_db):
        import sqlite3

        from backend.expenses.errors import GuestInUseError
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = service.create(owner_id, "Grandma")

        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(test_db)
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by,
                    paid_by_guest_id, created_at, updated_at)
               VALUES (?, ?, 'Cab', 30.0, 'EUR', ?, ?, ?, ?)""",
            (str(uuid.uuid4()), trip_id, owner_id, guest_id, now, now),
        )
        conn.commit()
        conn.close()

        with pytest.raises(GuestInUseError) as exc_info:
            service.delete(guest_id, owner_id)
        assert exc_info.value.guest_name == "Grandma"
        assert exc_info.value.expense_count == 1
        assert str(exc_info.value) == "Guest Grandma is used in 1 existing expense(s)"

    def test_deletes_when_unused_and_owned(self, test_db):
        from backend.expenses.guests_service import GuestService

        service = GuestService()
        owner_id = _seed_user(test_db)
        guest_id = service.create(owner_id, "Grandma")

        service.delete(guest_id, owner_id)
        assert service.list_mine(owner_id) == []
