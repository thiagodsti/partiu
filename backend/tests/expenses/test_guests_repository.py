"""Tests for backend.expenses.guests_repository (raw CRUD for the guests table)."""

import uuid
from datetime import UTC, datetime

from backend.tests.expenses.conftest import _seed_trip, _seed_user


class TestCreateAndList:
    def test_create_and_list_for_owner(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)

        guest_id = repo.create(owner_id, "Grandma")

        [guest] = repo.list_for_owner(owner_id)
        assert guest.id == guest_id
        assert guest.name == "Grandma"
        assert guest.owner_id == owner_id

    def test_isolates_by_owner(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner1 = _seed_user(test_db)
        owner2 = _seed_user(test_db)
        repo.create(owner1, "Grandma")

        assert len(repo.list_for_owner(owner1)) == 1
        assert repo.list_for_owner(owner2) == []


class TestListForTrip:
    def test_empty_when_no_guest_referenced(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create(owner_id, "Unused guest")

        assert repo.list_for_trip(trip_id) == []

    def test_includes_a_guest_on_the_roster(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")
        repo.add_to_trip(trip_id, guest_id)

        [guest] = repo.list_for_trip(trip_id)
        assert guest.id == guest_id

    def test_adding_twice_is_not_an_error(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")
        repo.add_to_trip(trip_id, guest_id)
        repo.add_to_trip(trip_id, guest_id)

        assert len(repo.list_for_trip(trip_id)) == 1

    def test_an_expense_reference_alone_no_longer_puts_a_guest_on_the_trip(self, test_db):
        """Membership is stated, not inferred — migration 0036. The service
        layer keeps the two in step by adding a named guest to the roster as it
        writes the expense (`ExpenseService._join_guests_to_trip`); a row poked
        straight into the table, as here, bypasses that on purpose."""
        import sqlite3

        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")

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

        assert repo.list_for_trip(trip_id) == []

    def test_removal_is_refused_while_an_expense_names_them(self, test_db):
        import sqlite3

        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")
        repo.add_to_trip(trip_id, guest_id)

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

        assert repo.is_used_on_trip(trip_id, guest_id) is True

    def test_an_unreferenced_guest_can_be_taken_off(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")
        repo.add_to_trip(trip_id, guest_id)

        assert repo.is_used_on_trip(trip_id, guest_id) is False
        repo.remove_from_trip(trip_id, guest_id)
        assert repo.list_for_trip(trip_id) == []

    def test_the_roster_is_per_trip(self, test_db):
        """The whole point: Jimmy on one trip is not Jimmy on another."""
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_a = _seed_trip(test_db, owner_id)
        trip_b = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Jimmy")
        repo.add_to_trip(trip_a, guest_id)

        assert [g.id for g in repo.list_for_trip(trip_a)] == [guest_id]
        assert repo.list_for_trip(trip_b) == []


class TestDeleteIfUnused:
    def test_deletes_and_returns_zero_when_unused(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        guest_id = repo.create(owner_id, "Grandma")

        assert repo.delete_if_unused(guest_id, owner_id) == 0
        assert repo.get(guest_id) is None

    def test_scoped_to_owner(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner1 = _seed_user(test_db)
        owner2 = _seed_user(test_db)
        guest_id = repo.create(owner1, "Grandma")

        repo.delete_if_unused(guest_id, owner2)
        assert repo.get(guest_id) is not None

    def test_counts_expense_used_as_payer_and_does_not_delete(self, test_db):
        import sqlite3

        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")

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

        assert repo.delete_if_unused(guest_id, owner_id) == 1
        assert repo.get(guest_id) is not None

    def test_counts_multiple_distinct_expenses(self, test_db):
        import sqlite3

        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")

        now = datetime.now(UTC).isoformat()
        conn = sqlite3.connect(test_db)
        expense_id_1 = str(uuid.uuid4())
        expense_id_2 = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by,
                    paid_by_guest_id, created_at, updated_at)
               VALUES (?, ?, 'Cab', 30.0, 'EUR', ?, ?, ?, ?)""",
            (expense_id_1, trip_id, owner_id, guest_id, now, now),
        )
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by, created_at, updated_at)
               VALUES (?, ?, 'Dinner', 40.0, 'EUR', ?, ?, ?)""",
            (expense_id_2, trip_id, owner_id, now, now),
        )
        conn.execute(
            "INSERT INTO trip_expense_participants (expense_id, guest_id) VALUES (?, ?)",
            (expense_id_2, guest_id),
        )
        conn.commit()
        conn.close()

        assert repo.delete_if_unused(guest_id, owner_id) == 2

    def test_counts_expense_once_when_both_payer_and_participant(self, test_db):
        import sqlite3

        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        guest_id = repo.create(owner_id, "Grandma")

        now = datetime.now(UTC).isoformat()
        expense_id = str(uuid.uuid4())
        conn = sqlite3.connect(test_db)
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by,
                    paid_by_guest_id, created_at, updated_at)
               VALUES (?, ?, 'Cab', 30.0, 'EUR', ?, ?, ?, ?)""",
            (expense_id, trip_id, owner_id, guest_id, now, now),
        )
        conn.execute(
            "INSERT INTO trip_expense_participants (expense_id, guest_id) VALUES (?, ?)",
            (expense_id, guest_id),
        )
        conn.commit()
        conn.close()

        assert repo.delete_if_unused(guest_id, owner_id) == 1


class TestUpdate:
    def test_update_renames_guest(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        guest_id = repo.create(owner_id, "Grandma")

        repo.update(guest_id, owner_id, "Grandpa")
        guest = repo.get(guest_id)
        assert guest is not None
        assert guest.name == "Grandpa"

    def test_update_scoped_to_owner(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner1 = _seed_user(test_db)
        owner2 = _seed_user(test_db)
        guest_id = repo.create(owner1, "Grandma")

        repo.update(guest_id, owner2, "Grandpa")
        guest = repo.get(guest_id)
        assert guest is not None
        assert guest.name == "Grandma"
