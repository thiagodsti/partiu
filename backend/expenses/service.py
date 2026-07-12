"""Use cases for trip expenses: trip-access checks + validation rules."""

import uuid

from .domain import SUPPORTED_CURRENCIES, Expense
from .repository import ExpenseRepository


class TripAccessError(Exception):
    """Raised when the user cannot access the given trip."""


class ExpenseNotFoundError(Exception):
    """Raised when the expense does not exist for the given trip."""


class ExpenseService:
    def __init__(self, repository: ExpenseRepository | None = None):
        self._repository = repository or ExpenseRepository()

    def list_expenses(self, trip_id: str, user_id: int) -> list[Expense]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def create_expense(
        self, trip_id: str, user_id: int, description: str, amount: float, currency: str
    ) -> str:
        """Validate then create an expense, returning its id.

        Validation runs before the trip-access check (matches the original route's
        behavior: bad input on someone else's trip returns 400, not 404).
        """
        clean_description = self._validate_description(description)
        self._validate_amount(amount)
        clean_currency = self._validate_currency(currency)

        self._check_access(trip_id, user_id)
        expense_id = str(uuid.uuid4())
        self._repository.create(
            expense_id, trip_id, clean_description, amount, clean_currency, user_id
        )
        return expense_id

    def update_expense(
        self,
        trip_id: str,
        expense_id: str,
        user_id: int,
        description: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
    ) -> None:
        self._check_access(trip_id, user_id)
        if not self._repository.exists(expense_id, trip_id):
            raise ExpenseNotFoundError(expense_id)

        updates: dict = {}
        if description is not None:
            updates["description"] = self._validate_description(description)
        if amount is not None:
            self._validate_amount(amount)
            updates["amount"] = amount
        if currency is not None:
            updates["currency"] = self._validate_currency(currency)

        if updates:
            self._repository.update(expense_id, trip_id, updates)

    def delete_expense(self, trip_id: str, expense_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if not self._repository.exists(expense_id, trip_id):
            raise ExpenseNotFoundError(expense_id)
        self._repository.delete(expense_id, trip_id)

    @staticmethod
    def _validate_description(description: str) -> str:
        clean = description.strip()
        if not clean:
            raise ValueError("Description cannot be empty")
        return clean

    @staticmethod
    def _validate_amount(amount: float) -> None:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")

    @staticmethod
    def _validate_currency(currency: str) -> str:
        upper = currency.upper()
        if upper not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}")
        return upper

    def _check_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


expense_service = ExpenseService()
