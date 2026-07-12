"""Repository for auth-feature data: the `users` columns needed by setup/login/2FA/
me/change-password, plus the `auth_attempts` table used for TOTP lockout.

Session cookies and their `sessions` table live in session.py instead — that's
cross-cutting infrastructure every route depends on, not part of this feature.
"""

from ..database import db_conn, db_write
from .domain import AuthUser, PasswordAndTotp, UserSummary
from .mappers import row_to_user_summary


class AuthRepository:
    # -- Users ------------------------------------------------------------

    def find_user_by_username(self, username: str) -> AuthUser | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, is_admin, smtp_recipient_address, totp_enabled, locale FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return AuthUser(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            is_admin=bool(row["is_admin"]),
            smtp_recipient_address=row["smtp_recipient_address"],
            totp_enabled=bool(row["totp_enabled"]),
            locale=row["locale"] or "en",
        )

    def get_user_with_totp_secret(self, user_id: int) -> AuthUser | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, username, is_admin, smtp_recipient_address, totp_secret, totp_enabled, locale FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return AuthUser(
            id=row["id"],
            username=row["username"],
            is_admin=bool(row["is_admin"]),
            smtp_recipient_address=row["smtp_recipient_address"],
            totp_enabled=bool(row["totp_enabled"]),
            locale=row["locale"] or "en",
            totp_secret=row["totp_secret"],
        )

    def get_user_summary(self, user_id: int) -> UserSummary | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, username, is_admin, smtp_recipient_address, totp_enabled, locale FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return row_to_user_summary(row) if row else None

    def get_totp_secret(self, user_id: int) -> str | None:
        with db_conn() as conn:
            row = conn.execute("SELECT totp_secret FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["totp_secret"] if row and row["totp_secret"] else None

    def set_totp_secret(self, user_id: int, secret: str) -> None:
        with db_write() as conn:
            conn.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user_id))

    def set_totp_enabled(self, user_id: int) -> None:
        with db_write() as conn:
            conn.execute("UPDATE users SET totp_enabled = 1 WHERE id = ?", (user_id,))

    def clear_totp(self, user_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE users SET totp_enabled = 0, totp_secret = NULL WHERE id = ?", (user_id,)
            )

    def get_password_and_totp(self, user_id: int) -> PasswordAndTotp | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT password_hash, totp_secret, totp_enabled FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return PasswordAndTotp(
            password_hash=row["password_hash"],
            totp_secret=row["totp_secret"],
            totp_enabled=bool(row["totp_enabled"]),
        )

    def update_locale(self, user_id: int, locale: str) -> None:
        with db_write() as conn:
            conn.execute("UPDATE users SET locale = ? WHERE id = ?", (locale, user_id))

    def update_password_hash(self, user_id: int, password_hash: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
            )

    def create_admin_user(
        self, username: str, password_hash: str, smtp_recipient_address: str | None
    ) -> int:
        """Create the first (admin) user. Raises on constraint violation."""
        with db_write() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, smtp_recipient_address) VALUES (?, ?, 1, ?)",
                (username, password_hash, smtp_recipient_address),
            )
            user_id = cursor.lastrowid
            # Assign any existing orphan data to this first admin
            conn.execute("UPDATE flights SET user_id = ? WHERE user_id IS NULL", (user_id,))
            conn.execute("UPDATE trips SET user_id = ? WHERE user_id IS NULL", (user_id,))
            conn.execute(
                "UPDATE email_sync_state SET user_id = ? WHERE user_id IS NULL", (user_id,)
            )
            return user_id

    # -- TOTP lockout (auth_attempts table) -----------------------------------

    def count_recent_totp_failures(self, user_id: int, window_minutes: int) -> int:
        with db_conn() as conn:
            return conn.execute(
                """SELECT COUNT(*) FROM auth_attempts
                   WHERE user_id = ? AND attempt_type = 'totp' AND success = 0
                   AND attempted_at > datetime('now', ?)""",
                (user_id, f"-{window_minutes} minutes"),
            ).fetchone()[0]

    def record_totp_attempt(self, user_id: int, success: bool) -> None:
        with db_write() as conn:
            conn.execute(
                "INSERT INTO auth_attempts (user_id, attempt_type, success) VALUES (?, 'totp', ?)",
                (user_id, 1 if success else 0),
            )
