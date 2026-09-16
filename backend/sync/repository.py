"""Repository for sync state, processed-email dedup tracking, and the user
credentials needed to run a sync."""

import sqlite3

from ..database import db_conn, db_write, get_global_setting
from .domain import SyncStateRow
from .mappers import row_to_sync_state

_STATE_COLUMNS = frozenset(
    {
        "status",
        "last_error",
        "last_synced_at",
        "emails_processed",
        "emails_total",
        "parser_version",
    }
)


class SyncRepository:
    def get_latest_state(self, user_id: int) -> SyncStateRow | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM email_sync_state WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        return row_to_sync_state(row) if row else None

    def upsert_state(self, user_id: int, **fields) -> None:
        """Insert or update the email_sync_state row for a user."""
        unknown = set(fields) - _STATE_COLUMNS
        if unknown:
            raise ValueError(f"Unknown email_sync_state columns: {unknown}")

        with db_write() as conn:
            existing = conn.execute(
                "SELECT id FROM email_sync_state WHERE user_id = ?", (user_id,)
            ).fetchone()
            if existing:
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(
                    f"UPDATE email_sync_state SET {set_clause} WHERE user_id = ?",
                    list(fields.values()) + [user_id],
                )
            else:
                cols = "user_id, " + ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in range(len(fields) + 1))
                conn.execute(
                    f"INSERT INTO email_sync_state ({cols}) VALUES ({placeholders})",
                    [user_id] + list(fields.values()),
                )

    def get_sync_interval_minutes(self) -> int:
        return int(get_global_setting("sync_interval_minutes", "10"))

    def reset_last_synced(self, user_id: int) -> None:
        """Forget where the last sync got to *and* which mails it has read.

        A full sync that kept the processed-mail ledger only re-fetched mail it
        then refused to look at, so a booking deleted by mistake — or read wrongly
        by an older parser — could never come back through it. Duplicates are
        prevented by the unique key on `flights.email_message_id`, not by the
        ledger, so clearing it costs a re-parse and nothing else.
        """
        with db_write() as conn:
            conn.execute(
                "UPDATE email_sync_state SET last_synced_at = NULL WHERE user_id = ?", (user_id,)
            )
            conn.execute("DELETE FROM processed_emails WHERE user_id = ?", (user_id,))

    def forget_emails(self, user_id: int, message_ids: list[str]) -> None:
        """Drop specific mails from the ledger — the ones behind a trashed flight."""
        if not message_ids:
            return
        with db_write() as conn:
            conn.executemany(
                "DELETE FROM processed_emails WHERE user_id = ? AND email_message_id = ?",
                [(user_id, mid) for mid in message_ids],
            )

    def get_sync_credentials(self, user_id: int) -> sqlite3.Row | None:
        with db_conn() as conn:
            return conn.execute(
                "SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

    def list_all_sync_credentials(self) -> list[sqlite3.Row]:
        """Return IMAP credentials for every user (used by the scheduled full sync sweep)."""
        with db_conn() as conn:
            return conn.execute(
                "SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users"
            ).fetchall()

    def is_email_processed(self, user_id: int, email_message_id: str) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_emails WHERE user_id = ? AND email_message_id = ?",
                (user_id, email_message_id),
            ).fetchone()
        return row is not None

    def mark_email_processed(self, user_id: int, email_message_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_emails (user_id, email_message_id) VALUES (?, ?)",
                (user_id, email_message_id),
            )
