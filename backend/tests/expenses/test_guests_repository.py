"""Tests for backend.expenses.guests_repository (raw CRUD for the guests table)."""

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

    def test_includes_guest_referenced_as_payer(self, test_db):
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

        [guest] = repo.list_for_trip(trip_id)
        assert guest.id == guest_id

    def test_includes_guest_referenced_as_participant(self, test_db):
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
                   (id, trip_id, description, amount, currency, created_by, created_at, updated_at)
               VALUES (?, ?, 'Lunch', 40.0, 'EUR', ?, ?, ?)""",
            (expense_id, trip_id, owner_id, now, now),
        )
        conn.execute(
            "INSERT INTO trip_expense_participants (expense_id, guest_id) VALUES (?, ?)",
            (expense_id, guest_id),
        )
        conn.commit()
        conn.close()

        [guest] = repo.list_for_trip(trip_id)
        assert guest.id == guest_id


class TestDelete:
    def test_delete_removes_guest(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        guest_id = repo.create(owner_id, "Grandma")

        repo.delete(guest_id, owner_id)
        assert repo.get(guest_id) is None

    def test_delete_scoped_to_owner(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner1 = _seed_user(test_db)
        owner2 = _seed_user(test_db)
        guest_id = repo.create(owner1, "Grandma")

        repo.delete(guest_id, owner2)
        assert repo.get(guest_id) is not None


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


class TestCountReferences:
    def test_zero_when_unused(self, test_db):
        from backend.expenses.guests_repository import GuestRepository

        repo = GuestRepository()
        owner_id = _seed_user(test_db)
        guest_id = repo.create(owner_id, "Grandma")

        assert repo.count_references(guest_id) == 0

    def test_counts_expense_used_as_payer(self, test_db):
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

        assert repo.count_references(guest_id) == 1

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

        assert repo.count_references(guest_id) == 2

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

        assert repo.count_references(guest_id) == 1
