"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import Expense
from .dto import ExpenseDTO


def row_to_expense(row: sqlite3.Row) -> Expense:
    return Expense(
        id=row["id"],
        trip_id=row["trip_id"],
        description=row["description"],
        amount=row["amount"],
        currency=row["currency"],
        created_by=row["created_by"],
        created_by_username=row["created_by_username"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def expense_to_dto(expense: Expense) -> ExpenseDTO:
    return ExpenseDTO(
        id=expense.id,
        trip_id=expense.trip_id,
        description=expense.description,
        amount=expense.amount,
        currency=expense.currency,
        created_by=expense.created_by,
        created_by_username=expense.created_by_username,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )
