"""Repository for the `guests` table (non-account trip participants).

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import Guest


def _row_to_guest(row) -> Guest:
    return Guest(
        id=row["id"], owner_id=row["owner_id"], name=row["name"], created_at=row["created_at"]
    )


class GuestRepository:
    def list_for_owner(self, owner_id: int) -> list[Guest]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, owner_id, name, created_at FROM guests WHERE owner_id = ? ORDER BY name ASC",
                (owner_id,),
            ).fetchall()
        return [_row_to_guest(r) for r in rows]

    def list_for_trip(self, trip_id: str) -> list[Guest]:
        """Guests referenced (as participant or payer) in any expense of this trip."""
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT g.id, g.owner_id, g.name, g.created_at
                   FROM guests g
                   WHERE g.id IN (
                       SELECT p.guest_id FROM trip_expense_participants p
                       JOIN trip_expenses e ON e.id = p.expense_id
                       WHERE e.trip_id = ? AND p.guest_id IS NOT NULL
                       UNION
                       SELECT paid_by_guest_id FROM trip_expenses
                       WHERE trip_id = ? AND paid_by_guest_id IS NOT NULL
                   )
                   ORDER BY g.name ASC""",
                (trip_id, trip_id),
            ).fetchall()
        return [_row_to_guest(r) for r in rows]

    def get(self, guest_id: int) -> Guest | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, owner_id, name, created_at FROM guests WHERE id = ?",
                (guest_id,),
            ).fetchone()
        return _row_to_guest(row) if row else None

    def create(self, owner_id: int, name: str) -> int:
        now = now_iso()
        with db_write() as conn:
            cursor = conn.execute(
                "INSERT INTO guests (owner_id, name, created_at) VALUES (?, ?, ?)",
                (owner_id, name, now),
            )
            return cursor.lastrowid

    def update(self, guest_id: int, owner_id: int, name: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE guests SET name = ? WHERE id = ? AND owner_id = ?",
                (name, guest_id, owner_id),
            )

    def delete_if_unused(self, guest_id: int, owner_id: int) -> int:
        """Delete the guest unless it's referenced by an expense, atomically — the
        reference count and the delete happen under the same write-lock hold, so a
        concurrent request can't tag the guest in a new expense between the check
        and the delete. Returns the reference count found (0 means deleted)."""
        with db_write() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT id) FROM (
                       SELECT expense_id AS id FROM trip_expense_participants WHERE guest_id = ?
                       UNION
                       SELECT id FROM trip_expenses WHERE paid_by_guest_id = ?
                   )""",
                (guest_id, guest_id),
            ).fetchone()
            count = row[0]
            if count == 0:
                conn.execute(
                    "DELETE FROM guests WHERE id = ? AND owner_id = ?", (guest_id, owner_id)
                )
            return count
