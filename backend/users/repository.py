"""Repository for the `users` table (admin user management)."""

import sqlite3

from ..database import db_conn, db_write
from .domain import User
from .mappers import row_to_user


class UserRepository:
    def list_credential_columns(self) -> list[sqlite3.Row]:
        """Return id + the at-rest-encrypted credential columns for every user
        (used by one-time crypto migrations at startup — see database.py's
        init_database() and crypto.migrate_legacy_encryption())."""
        with db_conn() as conn:
            return conn.execute(
                "SELECT id, gmail_app_password, immich_api_key FROM users"
            ).fetchall()

    def list_users(self) -> list[User]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, username, is_admin, smtp_recipient_address, totp_enabled, created_at FROM users ORDER BY id"
            ).fetchall()
        return [row_to_user(r) for r in rows]

    def exists(self, user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        return row is not None

    def find_by_username(self, username: str) -> User | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, username, is_admin, smtp_recipient_address, totp_enabled, created_at "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return row_to_user(row) if row else None

    def create_user(
        self,
        username: str,
        password_hash: str,
        is_admin: bool,
        smtp_recipient_address: str | None,
    ) -> int:
        """Returns the new user's id. Raises on constraint violation (e.g. duplicate username)."""
        with db_write() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, smtp_recipient_address) VALUES (?, ?, ?, ?)",
                (username, password_hash, 1 if is_admin else 0, smtp_recipient_address),
            )
            return cursor.lastrowid

    def update_user(self, user_id: int, updates: dict) -> None:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id = ?", (*updates.values(), user_id)
            )

    def delete_user(self, user_id: int) -> None:
        with db_write() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
