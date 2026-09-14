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
    """The `trip_budgets` table and its `trip_budget_members` rows.

    A budget is still stored per owner — keyed on (trip_id, user_id) — but it
    belongs to everyone in its member list, which is how two people travelling
    on one purse share a limit. The owner is always among the members, stored as
    a row like any other so the share query is one uniform join.
    """

    def get(self, trip_id: str, user_id: int) -> Budget | None:
        """The budget this user *owns* on this trip, if any. Resolution for
        display goes through `resolve` — a member who owns nothing still has a
        budget to look at."""
        with db_conn() as conn:
            row = conn.execute(
                """SELECT b.amount, b.currency, b.user_id, u.username
                     FROM trip_budgets b
                     LEFT JOIN users u ON u.id = b.user_id
                    WHERE b.trip_id = ? AND b.user_id = ?""",
                (trip_id, user_id),
            ).fetchone()
        return self._row_to_budget(row) if row else None

    def resolve(self, trip_id: str, user_id: int) -> Budget | None:
        """The budget that applies to this user on this trip: their own if they
        have one, otherwise one that names them as a member.

        Their own wins because setting a budget is a deliberate act and must not
        be overridden by someone adding you to theirs. `ORDER BY b.user_id` only
        keeps the answer stable if two different people have both named you;
        nothing in the UI creates that, but an arbitrary winner would make the
        figure flicker between reads.
        """
        own = self.get(trip_id, user_id)
        if own is not None:
            return own
        with db_conn() as conn:
            row = conn.execute(
                """SELECT b.amount, b.currency, b.user_id, u.username
                     FROM trip_budgets b
                     JOIN trip_budget_members m
                       ON m.trip_id = b.trip_id AND m.owner_user_id = b.user_id
                     LEFT JOIN users u ON u.id = b.user_id
                    WHERE b.trip_id = ? AND m.member_type = 'user' AND m.member_id = ?
                    ORDER BY b.user_id
                    LIMIT 1""",
                (trip_id, user_id),
            ).fetchone()
        return self._row_to_budget(row) if row else None

    @staticmethod
    def _row_to_budget(row) -> Budget:
        return Budget(
            amount=row["amount"],
            currency=row["currency"],
            owner_user_id=row["user_id"],
            owner_username=row["username"],
        )

    def list_members(self, trip_id: str, owner_user_id: int) -> list[tuple[str, int]]:
        """The (type, id) pairs a budget is shared with, owner included. Names
        are not joined here: the service already has the trip's participant list
        and resolves them against that, which is also what keeps a member who
        has since left the trip from being printed as a bare id."""
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT member_type, member_id FROM trip_budget_members
                    WHERE trip_id = ? AND owner_user_id = ?
                    ORDER BY member_type, member_id""",
                (trip_id, owner_user_id),
            ).fetchall()
        return [(row["member_type"], row["member_id"]) for row in rows]

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

    def replace_members(
        self, trip_id: str, owner_user_id: int, members: list[tuple[str, int]]
    ) -> None:
        """Wholesale, not a diff — the member list is a set the user chose, and
        the rows carry nothing else worth preserving."""
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_budget_members WHERE trip_id = ? AND owner_user_id = ?",
                (trip_id, owner_user_id),
            )
            conn.executemany(
                """INSERT OR IGNORE INTO trip_budget_members
                       (trip_id, owner_user_id, member_type, member_id)
                   VALUES (?, ?, ?, ?)""",
                [(trip_id, owner_user_id, m_type, m_id) for m_type, m_id in members],
            )

    def delete(self, trip_id: str, user_id: int) -> None:
        with db_write() as conn:
            # The FK cascades, but only while `PRAGMA foreign_keys` is on; the
            # member rows are dropped explicitly so the table cannot be left
            # holding rows for a budget that no longer exists.
            conn.execute(
                "DELETE FROM trip_budget_members WHERE trip_id = ? AND owner_user_id = ?",
                (trip_id, user_id),
            )
            conn.execute(
                "DELETE FROM trip_budgets WHERE trip_id = ? AND user_id = ?", (trip_id, user_id)
            )

    def resolve_for_trips(self, user_id: int, trip_ids: list[str]) -> dict[str, Budget]:
        """The budget that applies to this user on each of these trips, in one
        read — the bulk twin of `resolve`.

        The trips list renders dozens of cards; a budget fetched per card would
        be a request per row. Own-before-shared is expressed as `ORDER BY` plus
        a first-wins loop rather than two queries: `is_own` sorts a budget the
        user owns ahead of one that merely names them, and `b.user_id` keeps the
        loser deterministic when two people have both named them.
        """
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"""SELECT b.trip_id, b.amount, b.currency, b.user_id, u.username,
                           (b.user_id = ?) AS is_own
                      FROM trip_budgets b
                      LEFT JOIN trip_budget_members m
                        ON m.trip_id = b.trip_id AND m.owner_user_id = b.user_id
                       AND m.member_type = 'user' AND m.member_id = ?
                      LEFT JOIN users u ON u.id = b.user_id
                     WHERE b.trip_id IN ({placeholders})
                       AND (m.member_id IS NOT NULL OR b.user_id = ?)
                     ORDER BY b.trip_id, is_own DESC, b.user_id""",
                [user_id, user_id, *trip_ids, user_id],
            ).fetchall()
        out: dict[str, Budget] = {}
        for row in rows:
            out.setdefault(row["trip_id"], self._row_to_budget(row))
        return out

    def share_by_trip(self, owners: list[tuple[str, int]]) -> dict[tuple[str, str], float]:
        """(trip_id, currency) -> the combined share of the named budget's members.

        The bulk twin of `ExpenseService._share_by_currency`, which walks expense
        objects one trip at a time. Same rule in SQL: join each expense's
        participant rows to the budget's member rows and divide by how many
        participants the expense has, so an expense split four ways between four
        people contributes one quarter per member of the budget. An expense no
        member is tagged in never joins, so paying for other people still counts
        nothing — and `COUNT(*)` cannot be zero inside a group that exists, so
        the division is safe.

        `owners` is (trip_id, owner_user_id) pairs rather than a single user,
        because the budget that applies on each trip may belong to a different
        person — a shared one is owned by whoever created it.
        """
        if not owners:
            return {}
        values = ",".join(["(?, ?)"] * len(owners))
        params: list[object] = []
        for trip_id, owner_user_id in owners:
            params.extend((trip_id, owner_user_id))
        with db_conn() as conn:
            rows = conn.execute(
                f"""WITH sel(trip_id, owner_user_id) AS (VALUES {values}),
                         -- The owner is unioned in rather than assumed present:
                         -- `set_budget` always writes their row and migration
                         -- 0031 backfills it, so this changes nothing in
                         -- practice — but an inner join on the members table
                         -- alone would silently value a memberless budget at
                         -- zero, while the single-trip path re-adds the owner
                         -- and reports the real figure. The two must not be
                         -- able to disagree.
                         mem(trip_id, owner_user_id, member_type, member_id) AS (
                             SELECT trip_id, owner_user_id, member_type, member_id
                               FROM trip_budget_members
                             UNION
                             SELECT trip_id, owner_user_id, 'user', owner_user_id FROM sel
                         )
                    SELECT e.trip_id, e.currency, SUM(e.amount * 1.0 / pc.n) AS share
                      FROM trip_expenses e
                      JOIN sel ON sel.trip_id = e.trip_id
                      JOIN trip_expense_participants p ON p.expense_id = e.id
                      JOIN mem m
                        ON m.trip_id = sel.trip_id
                       AND m.owner_user_id = sel.owner_user_id
                       AND ((m.member_type = 'user' AND m.member_id = p.user_id)
                            OR (m.member_type = 'guest' AND m.member_id = p.guest_id))
                      JOIN (
                            SELECT expense_id, COUNT(*) AS n
                              FROM trip_expense_participants
                             GROUP BY expense_id
                           ) pc ON pc.expense_id = e.id
                     GROUP BY e.trip_id, e.currency""",
                params,
            ).fetchall()
        return {(row["trip_id"], row["currency"]): row["share"] for row in rows}
