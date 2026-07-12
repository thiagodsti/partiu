"""Repository for everything push-delivery related:

- push subscription CRUD (``push_subscriptions`` table)
- VAPID key storage (``global_settings`` table)
- the unread push-badge counter (``users.notif_unread``)
- the send-dedup log (``notification_log`` table)
- per-user notification preference columns (``users.notif_*``)
"""

from datetime import UTC, datetime

from ..database import db_conn, db_write, get_global_setting, set_global_setting
from .domain import PushSubscription
from .mappers import row_to_push_subscription

PREFERENCE_COLUMNS = {
    "flight_reminder": "notif_flight_reminder",
    "checkin_reminder": "notif_checkin_reminder",
    "trip_reminder": "notif_trip_reminder",
    "delay_alert": "notif_delay_alert",
    "boarding_pass": "notif_boarding_pass",
    "new_flight": "notif_new_flight",
}


class PushRepository:
    # -- Subscriptions --------------------------------------------------

    def save_subscription(
        self, user_id: int, subscription: PushSubscription, user_agent: str = ""
    ) -> None:
        """Upsert a push subscription for a user/device pair."""
        with db_write() as conn:
            conn.execute(
                """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, endpoint) DO UPDATE SET
                     p256dh = excluded.p256dh,
                     auth = excluded.auth,
                     user_agent = excluded.user_agent""",
                (
                    user_id,
                    subscription.endpoint,
                    subscription.p256dh,
                    subscription.auth,
                    user_agent,
                ),
            )

    def delete_subscription(self, user_id: int, endpoint: str) -> None:
        """Remove a specific push subscription."""
        with db_write() as conn:
            conn.execute(
                "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
                (user_id, endpoint),
            )

    def get_subscriptions(self, user_id: int) -> list[PushSubscription]:
        """Return all active push subscriptions for a user."""
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [row_to_push_subscription(r) for r in rows]

    # -- VAPID keys -------------------------------------------------------

    def get_vapid_settings(self) -> tuple[str, str, str]:
        """Return (private_key, public_key, subject) as stored in global_settings."""
        private = get_global_setting("vapid_private_key")
        public = get_global_setting("vapid_public_key")
        subject = get_global_setting("vapid_subject")
        return private, public, subject

    def save_vapid_keys(self, private_key: str, public_key: str) -> None:
        set_global_setting("vapid_private_key", private_key)
        set_global_setting("vapid_public_key", public_key)

    # -- Unread badge counter --------------------------------------------

    def get_unread_count(self, user_id: int) -> int:
        """Return the current unread notification count for a user."""
        with db_conn() as conn:
            row = conn.execute("SELECT notif_unread FROM users WHERE id = ?", (user_id,)).fetchone()
        return int(row["notif_unread"]) if row else 0

    def increment_unread(self, user_id: int) -> int:
        """Increment and return the new unread count."""
        with db_write() as conn:
            conn.execute(
                "UPDATE users SET notif_unread = notif_unread + 1 WHERE id = ?", (user_id,)
            )
            row = conn.execute("SELECT notif_unread FROM users WHERE id = ?", (user_id,)).fetchone()
        return int(row["notif_unread"]) if row else 1

    def clear_unread(self, user_id: int) -> None:
        """Reset the unread notification counter to zero."""
        with db_write() as conn:
            conn.execute("UPDATE users SET notif_unread = 0 WHERE id = ?", (user_id,))

    # -- Dedup log ---------------------------------------------------------

    def already_sent(self, user_id: int, flight_id: str, notif_type: str) -> bool:
        """Return True if this notification was already sent."""
        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM notification_log WHERE user_id = ? AND flight_id = ? AND notif_type = ?",
                (user_id, flight_id, notif_type),
            ).fetchone()
        return row is not None

    def log_sent(self, user_id: int, flight_id: str, notif_type: str) -> None:
        """Record that a notification was sent (INSERT OR IGNORE for idempotency)."""
        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO notification_log (user_id, flight_id, notif_type, sent_at) VALUES (?, ?, ?, ?)",
                (user_id, flight_id, notif_type, datetime.now(UTC).isoformat()),
            )

    # -- Preferences ---------------------------------------------------------

    def is_enabled(self, user_id: int, pref_key: str) -> bool:
        """Whether a named notification preference (see PREFERENCE_COLUMNS) is on
        for a user. False if the user doesn't exist."""
        column = PREFERENCE_COLUMNS[pref_key]
        with db_conn() as conn:
            row = conn.execute(f"SELECT {column} FROM users WHERE id = ?", (user_id,)).fetchone()
        return bool(row[column]) if row else False

    def get_locale(self, user_id: int) -> str:
        with db_conn() as conn:
            row = conn.execute("SELECT locale FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["locale"] if row and row["locale"] else "en"

    def update_preferences(self, user_id: int, updates: dict[str, bool]) -> None:
        """Update a subset of notification preference columns.

        ``updates`` keys must already be validated against PREFERENCE_COLUMNS by the caller.
        """
        columns = [PREFERENCE_COLUMNS[key] for key in updates]
        set_clause = ", ".join(f"{col} = ?" for col in columns)
        values = [int(v) for v in updates.values()]
        with db_write() as conn:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*values, user_id))
