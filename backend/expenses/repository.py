"""Repository for the `trip_expenses` and `trip_expense_participants` tables.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

import sqlite3

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import Budget, Expense
from .mappers import row_to_expense

_EXPENSE_SELECT = """
    SELECT e.id, e.trip_id, e.description, e.amount, e.currency,
           e.created_by, e.created_at, e.updated_at,
           e.paid_by_user_id, e.paid_by_guest_id,
           u.username AS created_by_username,
           pu.username AS paid_by_user_name,
           pg.name AS paid_by_guest_name
    FROM trip_expenses e
    LEFT JOIN users u ON u.id = e.created_by
    LEFT JOIN users pu ON pu.id = e.paid_by_user_id
    LEFT JOIN guests pg ON pg.id = e.paid_by_guest_id
"""


class ExpenseRepository:
    def list_for_trip(self, trip_id: str) -> list[Expense]:
        with db_conn() as conn:
            rows = conn.execute(
                _EXPENSE_SELECT + " WHERE e.trip_id = ? ORDER BY e.created_at ASC",
                (trip_id,),
            ).fetchall()
            participants_by_expense = self._fetch_participants(conn, [r["id"] for r in rows])
        return [row_to_expense(r, participants_by_expense.get(r["id"], [])) for r in rows]

    @staticmethod
    def _fetch_participants(
        conn: sqlite3.Connection, expense_ids: list[str]
    ) -> dict[str, list[sqlite3.Row]]:
        if not expense_ids:
            return {}
        placeholders = ",".join("?" * len(expense_ids))
        rows = conn.execute(
            f"""SELECT p.expense_id, p.user_id, p.guest_id,
                       u.username AS user_name, g.name AS guest_name
                FROM trip_expense_participants p
                LEFT JOIN users u ON u.id = p.user_id
                LEFT JOIN guests g ON g.id = p.guest_id
                WHERE p.expense_id IN ({placeholders})""",
            expense_ids,
        ).fetchall()
        result: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            result.setdefault(r["expense_id"], []).append(r)
        return result

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
        paid_by_user_id: int | None,
        paid_by_guest_id: int | None,
        participants: list[tuple[str, int]],
    ) -> None:
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_expenses
                       (id, trip_id, description, amount, currency, created_by,
                        paid_by_user_id, paid_by_guest_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    expense_id,
                    trip_id,
                    description,
                    amount,
                    currency,
                    created_by,
                    paid_by_user_id,
                    paid_by_guest_id,
                    now,
                    now,
                ),
            )
            self._insert_participants(conn, expense_id, participants)

    @staticmethod
    def _insert_participants(
        conn: sqlite3.Connection, expense_id: str, participants: list[tuple[str, int]]
    ) -> None:
        conn.executemany(
            "INSERT INTO trip_expense_participants (expense_id, user_id, guest_id) VALUES (?, ?, ?)",
            [
                (expense_id, pid, None) if ptype == "user" else (expense_id, None, pid)
                for ptype, pid in participants
            ],
        )

    def update(self, expense_id: str, trip_id: str, updates: dict) -> None:
        """``updates`` maps column name (description/amount/currency/paid_by_user_id/
        paid_by_guest_id) to its new value."""
        all_updates = {**updates, "updated_at": now_iso()}
        set_clause = ", ".join(f"{col} = ?" for col in all_updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE trip_expenses SET {set_clause} WHERE id = ? AND trip_id = ?",
                (*all_updates.values(), expense_id, trip_id),
            )

    def replace_participants(self, expense_id: str, participants: list[tuple[str, int]]) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_expense_participants WHERE expense_id = ?", (expense_id,)
            )
            self._insert_participants(conn, expense_id, participants)

    def delete(self, expense_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_expenses WHERE id = ? AND trip_id = ?",
                (expense_id, trip_id),
            )


class BudgetRepository:
    """The `trip_budgets` table. Keyed on (trip_id, user_id): a budget belongs
    to a person, not to a trip, so two collaborators each keep their own."""

    def get(self, trip_id: str, user_id: int) -> Budget | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT amount, currency FROM trip_budgets WHERE trip_id = ? AND user_id = ?",
                (trip_id, user_id),
            ).fetchone()
        return Budget(amount=row["amount"], currency=row["currency"]) if row else None

    def set(self, trip_id: str, user_id: int, amount: float, currency: str) -> None:
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_budgets (trip_id, user_id, amount, currency, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(trip_id, user_id) DO UPDATE SET
                       amount = excluded.amount,
                       currency = excluded.currency,
                       updated_at = excluded.updated_at""",
                (trip_id, user_id, amount, currency, now, now),
            )

    def delete(self, trip_id: str, user_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_budgets WHERE trip_id = ? AND user_id = ?", (trip_id, user_id)
            )

    def list_for_user(self, user_id: int, trip_ids: list[str]) -> dict[str, Budget]:
        """Every budget this user has set across these trips, in one read.

        The trips list renders dozens of cards; a budget fetched per card would
        be a request per row.
        """
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"""SELECT trip_id, amount, currency FROM trip_budgets
                    WHERE user_id = ? AND trip_id IN ({placeholders})""",
                [user_id, *trip_ids],
            ).fetchall()
        return {
            row["trip_id"]: Budget(amount=row["amount"], currency=row["currency"]) for row in rows
        }

    def own_share_by_trip(self, user_id: int, trip_ids: list[str]) -> dict[tuple[str, str], float]:
        """(trip_id, currency) -> the user's equal share of what they are in.

        The bulk twin of `ExpenseService._own_share_by_currency`, which walks
        expense objects one trip at a time. Same rule in SQL: join the caller's
        participant rows, divide each expense by how many participants it has.
        An expense the caller is not tagged in never joins, so paying for other
        people does not count — and `COUNT(*)` cannot be zero inside a group
        that exists, so the division is safe.
        """
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"""SELECT e.trip_id, e.currency, SUM(e.amount * 1.0 / pc.n) AS share
                      FROM trip_expenses e
                      JOIN trip_expense_participants p
                        ON p.expense_id = e.id AND p.user_id = ?
                      JOIN (
                            SELECT expense_id, COUNT(*) AS n
                              FROM trip_expense_participants
                             GROUP BY expense_id
                           ) pc ON pc.expense_id = e.id
                     WHERE e.trip_id IN ({placeholders})
                     GROUP BY e.trip_id, e.currency""",
                [user_id, *trip_ids],
            ).fetchall()
        return {(row["trip_id"], row["currency"]): row["share"] for row in rows}
