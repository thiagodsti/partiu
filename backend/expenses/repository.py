"""Repository for the `trip_expenses` table.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import Expense
from .mappers import row_to_expense


class ExpenseRepository:
    def list_for_trip(self, trip_id: str) -> list[Expense]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT e.id, e.trip_id, e.description, e.amount, e.currency,
                          e.created_by, e.created_at, e.updated_at,
                          u.username AS created_by_username
                   FROM trip_expenses e
                   LEFT JOIN users u ON u.id = e.created_by
                   WHERE e.trip_id = ?
                   ORDER BY e.created_at ASC""",
                (trip_id,),
            ).fetchall()
        return [row_to_expense(r) for r in rows]

    def exists(self, expense_id: str, trip_id: str) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM trip_expenses WHERE id = ? AND trip_id = ?",
                (expense_id, trip_id),
            ).fetchone()
        return row is not None

    def create(
        self,
        expense_id: str,
        trip_id: str,
        description: str,
        amount: float,
        currency: str,
        created_by: int,
    ) -> None:
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_expenses
                       (id, trip_id, description, amount, currency, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (expense_id, trip_id, description, amount, currency, created_by, now, now),
            )

    def update(self, expense_id: str, trip_id: str, updates: dict) -> None:
        """``updates`` maps column name ('description' | 'amount' | 'currency') to its new value."""
        all_updates = {**updates, "updated_at": now_iso()}
        set_clause = ", ".join(f"{col} = ?" for col in all_updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE trip_expenses SET {set_clause} WHERE id = ? AND trip_id = ?",
                (*all_updates.values(), expense_id, trip_id),
            )

    def delete(self, expense_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_expenses WHERE id = ? AND trip_id = ?",
                (expense_id, trip_id),
            )
