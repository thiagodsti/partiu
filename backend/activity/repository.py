"""Repository for the `activity_log` table."""

import json
import sqlite3

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import ActivityEntry


def _row_to_entry(row: sqlite3.Row) -> ActivityEntry:
    try:
        details = json.loads(row["details"]) if row["details"] else {}
    except ValueError:
        details = {}
    return ActivityEntry(
        id=row["id"],
        user_id=row["user_id"],
        action=row["action"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        label=row["label"],
        details=details,
        created_at=row["created_at"],
    )


class ActivityRepository:
    def record(
        self,
        user_id: int,
        action: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        label: str | None = None,
        details: dict | None = None,
    ) -> int:
        with db_write() as conn:
            cur = conn.execute(
                """INSERT INTO activity_log
                   (user_id, action, entity_type, entity_id, label, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    action,
                    entity_type,
                    entity_id,
                    label,
                    json.dumps(details or {}, ensure_ascii=False),
                    now_iso(),
                ),
            )
            return int(cur.lastrowid or 0)

    def list_for_user(self, user_id: int, limit: int = 100) -> list[ActivityEntry]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]
