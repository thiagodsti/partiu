"""Tests for backend.expenses.service (trip-access checks + validation rules)."""

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


class TestListExpenses:
    def test_raises_when_no_access(self, test_db):
        from backend.expenses.service import ExpenseService, TripAccessError

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_expenses(trip_id, other_id)


class TestCreateExpense:
    def test_rejects_blank_description(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "   ", 10.0, "EUR")

    def test_rejects_zero_amount(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "Hotel", 0.0, "EUR")

    def test_rejects_negative_amount(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "Refund", -50.0, "EUR")

    def test_rejects_unsupported_currency(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, user_id, "Item", 10.0, "XYZ")

    def test_uppercases_currency(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        service.create_expense(trip_id, user_id, "Taxi", 20.0, "usd")
        [expense] = service.list_expenses(trip_id, user_id)
        assert expense.currency == "USD"

    def test_strips_description(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        service.create_expense(trip_id, user_id, "  Hotel  ", 10.0, "EUR")
        [expense] = service.list_expenses(trip_id, user_id)
        assert expense.description == "Hotel"

    def test_validation_runs_before_access_check(self, test_db):
        """Bad input on someone else's trip should 400 (ValueError), not 404 (TripAccessError) —
        matches the original route's ordering."""
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(ValueError):
            service.create_expense(trip_id, other_id, "", 10.0, "EUR")

    def test_raises_access_error_when_input_valid(self, test_db):
        from backend.expenses.service import ExpenseService, TripAccessError

        service = ExpenseService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.create_expense(trip_id, other_id, "Item", 10.0, "EUR")


class TestUpdateExpense:
    def test_raises_when_expense_missing(self, test_db):
        from backend.expenses.service import ExpenseNotFoundError, ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ExpenseNotFoundError):
            service.update_expense(trip_id, "nonexistent-id", user_id, amount=100.0)

    def test_rejects_blank_description(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = service.create_expense(trip_id, user_id, "Hotel", 10.0, "EUR")

        with pytest.raises(ValueError):
            service.update_expense(trip_id, expense_id, user_id, description="   ")

    def test_updates_amount(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = service.create_expense(trip_id, user_id, "Hotel", 100.0, "EUR")

        service.update_expense(trip_id, expense_id, user_id, amount=250.0)
        [expense] = service.list_expenses(trip_id, user_id)
        assert expense.amount == 250.0


class TestDeleteExpense:
    def test_raises_when_expense_missing(self, test_db):
        from backend.expenses.service import ExpenseNotFoundError, ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(ExpenseNotFoundError):
            service.delete_expense(trip_id, "nonexistent-id", user_id)

    def test_deletes_existing_expense(self, test_db):
        from backend.expenses.service import ExpenseService

        service = ExpenseService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        expense_id = service.create_expense(trip_id, user_id, "Hotel", 10.0, "EUR")

        service.delete_expense(trip_id, expense_id, user_id)
        assert service.list_expenses(trip_id, user_id) == []
