"""Repository for the `trash` table plus the snapshot/restore transactions."""

import json
import sqlite3
from collections import OrderedDict

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import TrashItem
from .snapshot import collect_graph, restore_graph


def _row_to_item(row: sqlite3.Row) -> TrashItem:
    try:
        summary = json.loads(row["summary"]) if row["summary"] else {}
    except ValueError:
        summary = {}
    return TrashItem(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        entity_id=row["entity_id"],
        label=row["label"],
        summary=summary,
        deleted_at=row["deleted_at"],
    )


class TrashRepository:
    def snapshot_trip(self, trip_id: str) -> OrderedDict[str, list[dict]]:
        with db_conn() as conn:
            return collect_graph(conn, "trips", trip_id)

    def snapshot_flight(self, flight_id: str) -> OrderedDict[str, list[dict]]:
        with db_conn() as conn:
            return collect_graph(conn, "flights", flight_id)

    def add(
        self, user_id: int, kind: str, entity_id: str, label: str, summary: dict, payload: dict
    ) -> int:
        with db_write() as conn:
            cur = conn.execute(
                """INSERT INTO trash (user_id, kind, entity_id, label, summary, payload, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    kind,
                    entity_id,
                    label,
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    now_iso(),
                ),
            )
            return int(cur.lastrowid or 0)

    def list_for_user(self, user_id: int) -> list[TrashItem]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, user_id, kind, entity_id, label, summary, deleted_at FROM trash "
                "WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_owned(self, trash_id: int, user_id: int) -> TrashItem | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, user_id, kind, entity_id, label, summary, deleted_at FROM trash "
                "WHERE id = ? AND user_id = ?",
                (trash_id, user_id),
            ).fetchone()
        return _row_to_item(row) if row else None

    def payload(self, trash_id: int, user_id: int) -> dict[str, list[dict]] | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM trash WHERE id = ? AND user_id = ?", (trash_id, user_id)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["payload"], object_pairs_hook=OrderedDict)

    def restore_and_remove(
        self, trash_id: int, graph: dict[str, list[dict]]
    ) -> dict[str, dict[str, int]]:
        """Re-insert the snapshot and drop the trash row in one transaction."""
        with db_write() as conn:
            result = restore_graph(conn, graph)
            conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
        return result

    def remove(self, trash_id: int, user_id: int) -> None:
        with db_write() as conn:
            conn.execute("DELETE FROM trash WHERE id = ? AND user_id = ?", (trash_id, user_id))
