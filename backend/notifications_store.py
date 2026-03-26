"""
In-app notification store.

Functions for creating, listing, reading and deleting notification records
in the ``notifications`` table.  Push delivery is handled separately by
``push.py`` — these records are the persistent, in-app inbox.
"""

import logging

from .database import db_conn, db_write
from .utils import now_iso

logger = logging.getLogger(__name__)

_MAX_PER_USER = 100  # keep the inbox from growing unbounded


def create_notification(
    user_id: int,
    notif_type: str,
    title: str,
    body: str = "",
    url: str = "/",
) -> int:
    """Insert a notification record and return its id.

    Also increments the ``notif_unread`` push-badge counter so the next push
    includes the correct badge number.
    """
    with db_write() as conn:
        cursor = conn.execute(
            """INSERT INTO notifications (user_id, type, title, body, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, notif_type, title, body, url, now_iso()),
        )
        new_id = cursor.lastrowid

        # Keep the inbox bounded — delete oldest beyond the limit
        conn.execute(
            """DELETE FROM notifications WHERE user_id = ? AND id NOT IN (
               SELECT id FROM notifications WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?)""",
            (user_id, user_id, _MAX_PER_USER),
        )

        # Bump the push-badge counter
        conn.execute("UPDATE users SET notif_unread = notif_unread + 1 WHERE id = ?", (user_id,))

    return new_id


def list_notifications(user_id: int, limit: int = 50) -> list[dict]:
    """Return the most recent notifications for a user, newest first."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT id, type, title, body, url, read, created_at
               FROM notifications WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_unread_count(user_id: int) -> int:
    """Return the number of unread notifications."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = ? AND read = 0",
            (user_id,),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def mark_read(notification_id: int, user_id: int) -> bool:
    """Mark a single notification as read. Returns True if found."""
    with db_write() as conn:
        conn.execute(
            "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )
        row = conn.execute(
            "SELECT id FROM notifications WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        ).fetchone()
    return row is not None


def mark_all_read(user_id: int) -> int:
    """Mark all unread notifications as read. Returns count updated."""
    with db_write() as conn:
        conn.execute(
            "UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0",
            (user_id,),
        )
        row = conn.execute("SELECT changes() AS n").fetchone()
    return int(row["n"]) if row else 0


def delete_notification(notification_id: int, user_id: int) -> bool:
    """Delete a notification. Returns True if it existed."""
    with db_write() as conn:
        row = conn.execute(
            "SELECT id FROM notifications WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "DELETE FROM notifications WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )
    return True
