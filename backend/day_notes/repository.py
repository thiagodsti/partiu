"""Repository for the `trip_day_notes` table.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import DayNote
from .mappers import row_to_day_note


class DayNoteRepository:
    def list_for_trip(self, trip_id: str) -> list[DayNote]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT dn.date, dn.content, dn.updated_at, u.username AS updated_by_username
                   FROM trip_day_notes dn
                   LEFT JOIN users u ON u.id = dn.updated_by
                   WHERE dn.trip_id = ?
                   ORDER BY dn.date ASC""",
                (trip_id,),
            ).fetchall()
        return [row_to_day_note(r) for r in rows]

    def upsert(self, trip_id: str, date: str, content: str, updated_by: int) -> None:
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_day_notes (trip_id, date, content, updated_at, updated_by)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(trip_id, date) DO UPDATE SET
                       content = excluded.content,
                       updated_at = excluded.updated_at,
                       updated_by = excluded.updated_by""",
                (trip_id, date, content, now_iso(), updated_by),
            )
