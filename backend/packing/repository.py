"""Repository for the `packing_items` table.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import PackingItem
from .mappers import row_to_item


class PackingRepository:
    def list_for_trip(self, trip_id: str) -> list[PackingItem]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT id, trip_id, text, checked, sort_order, created_by, created_at
                   FROM packing_items
                   WHERE trip_id = ?
                   ORDER BY sort_order ASC, created_at ASC""",
                (trip_id,),
            ).fetchall()
        return [row_to_item(r) for r in rows]

    def get(self, item_id: str, trip_id: str) -> PackingItem | None:
        with db_conn() as conn:
            row = conn.execute(
                """SELECT id, trip_id, text, checked, sort_order, created_by, created_at
                   FROM packing_items WHERE id = ? AND trip_id = ?""",
                (item_id, trip_id),
            ).fetchone()
        return row_to_item(row) if row else None

    def create(self, item_id: str, trip_id: str, text: str, created_by: int) -> None:
        with db_write() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM packing_items WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO packing_items (id, trip_id, text, checked, sort_order, created_by, created_at)
                   VALUES (?, ?, ?, 0, ?, ?, ?)""",
                (item_id, trip_id, text, max_order + 1, created_by, now_iso()),
            )

    def update(self, item_id: str, trip_id: str, updates: dict) -> None:
        """``updates`` maps column name ('text' | 'checked') to its new value."""
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE packing_items SET {set_clause} WHERE id = ? AND trip_id = ?",
                (*updates.values(), item_id, trip_id),
            )

    def delete(self, item_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM packing_items WHERE id = ? AND trip_id = ?",
                (item_id, trip_id),
            )

    def clear_checked(self, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM packing_items WHERE trip_id = ? AND checked = 1",
                (trip_id,),
            )
