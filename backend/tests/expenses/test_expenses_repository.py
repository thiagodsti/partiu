"""Tests for backend.expenses.repository (raw CRUD for trip_expenses / trip_expense_participants)."""

import uuid

from backend.tests.expenses.conftest import _seed_guest, _seed_trip, _seed_user


def _create(repo, expense_id, trip_id, description, amount, currency, user_id, participants=None):
    """Convenience wrapper: defaults paid_by=user_id, participants=[user_id] as a user."""
    repo.create(
        expense_id,
        trip_id,
        description,
        amount,
        currency,
        user_id,
        user_id,
        None,
        participants if participants is not None else [("user", user_id)],
    )


class TestCreate:
    def test_create_and_list(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = str(uuid.uuid4())

        _create(repo, expense_id, trip_id, "Hotel", 500.0, "EUR", user_id)

        expenses = repo.list_for_trip(trip_id)
        assert len(expenses) == 1
        assert expenses[0].id == expense_id
        assert expenses[0].description == "Hotel"
        assert expenses[0].amount == 500.0
        assert expenses[0].currency == "EUR"
        assert expenses[0].created_by == user_id

    def test_created_by_username_is_joined(self, test_db):
        import sqlite3

        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        conn = sqlite3.connect(test_db)
        username = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        conn.close()

        _create(repo, str(uuid.uuid4()), trip_id, "Hotel", 500.0, "EUR", user_id)
        [expense] = repo.list_for_trip(trip_id)
        assert expense.created_by_username == username

    def test_isolates_by_trip(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip1 = _seed_trip(test_db, user_id)
        trip2 = _seed_trip(test_db, user_id)
        _create(repo, str(uuid.uuid4()), trip1, "For trip 1", 10.0, "EUR", user_id)

        assert len(repo.list_for_trip(trip1)) == 1
        assert repo.list_for_trip(trip2) == []

    def test_paid_by_user_is_populated(self, test_db):
        import sqlite3

        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        conn = sqlite3.connect(test_db)
        username = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        conn.close()

        _create(repo, str(uuid.uuid4()), trip_id, "Hotel", 500.0, "EUR", user_id)
        [expense] = repo.list_for_trip(trip_id)
        assert expense.paid_by.type == "user"
        assert expense.paid_by.id == user_id
        assert expense.paid_by.name == username

    def test_paid_by_guest_is_populated(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        guest_id = _seed_guest(test_db, user_id, "Grandma")

        repo.create(
            str(uuid.uuid4()),
            trip_id,
            "Cab",
            30.0,
            "EUR",
            user_id,
            None,
            guest_id,
            [("user", user_id)],
        )
        [expense] = repo.list_for_trip(trip_id)
        assert expense.paid_by.type == "guest"
        assert expense.paid_by.id == guest_id
        assert expense.paid_by.name == "Grandma"

    def test_participants_include_users_and_guests(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        guest_id = _seed_guest(test_db, user_id, "Grandma")

        _create(
            repo,
            str(uuid.uuid4()),
            trip_id,
            "Lunch",
            100.0,
            "EUR",
            user_id,
            participants=[("user", user_id), ("user", other_id), ("guest", guest_id)],
        )
        [expense] = repo.list_for_trip(trip_id)
        keys = {(p.type, p.id) for p in expense.participants}
        assert keys == {("user", user_id), ("user", other_id), ("guest", guest_id)}
        names = {p.name for p in expense.participants}
        assert "Grandma" in names


class TestExists:
    def test_true_for_existing(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = str(uuid.uuid4())
        _create(repo, expense_id, trip_id, "Hotel", 10.0, "EUR", user_id)

        assert repo.exists(expense_id, trip_id) is True

    def test_false_for_nonexistent(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        assert repo.exists("nonexistent-id", trip_id) is False


class TestUpdate:
    def test_update_fields_and_bumps_updated_at(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = str(uuid.uuid4())
        _create(repo, expense_id, trip_id, "Old", 10.0, "EUR", user_id)
        [before] = repo.list_for_trip(trip_id)

        repo.update(expense_id, trip_id, {"description": "New", "amount": 20.0})

        [after] = repo.list_for_trip(trip_id)
        assert after.description == "New"
        assert after.amount == 20.0
        assert after.updated_at >= before.updated_at

    def test_update_paid_by_columns(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = str(uuid.uuid4())
        _create(repo, expense_id, trip_id, "Hotel", 10.0, "EUR", user_id)

        repo.update(expense_id, trip_id, {"paid_by_user_id": other_id, "paid_by_guest_id": None})

        [after] = repo.list_for_trip(trip_id)
        assert after.paid_by.type == "user"
        assert after.paid_by.id == other_id

    def test_replace_participants(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = str(uuid.uuid4())
        _create(repo, expense_id, trip_id, "Hotel", 10.0, "EUR", user_id)

        repo.replace_participants(expense_id, [("user", other_id)])

        [after] = repo.list_for_trip(trip_id)
        assert [(p.type, p.id) for p in after.participants] == [("user", other_id)]


class TestDelete:
    def test_delete_removes_expense(self, test_db):
        from backend.expenses.repository import ExpenseRepository

        repo = ExpenseRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = str(uuid.uuid4())
        _create(repo, expense_id, trip_id, "Hotel", 10.0, "EUR", user_id)

        repo.delete(expense_id, trip_id)
        assert repo.exists(expense_id, trip_id) is False
