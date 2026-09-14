"""Tests for backend.auth.repository (users columns for the auth feature + auth_attempts)."""

import itertools
from datetime import UTC, datetime

_user_counter = itertools.count(1)


def _seed_user(db_path: str, **overrides) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = overrides.pop("username", f"testuser{next(_user_counter)}")
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if overrides:
        set_clause = ", ".join(f"{k} = ?" for k in overrides)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*overrides.values(), user_id))
        conn.commit()
    conn.close()
    return user_id


class TestFindUserByUsername:
    def test_returns_user(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        _seed_user(test_db, username="alice")

        user = repo.find_user_by_username("alice")
        assert user is not None
        assert user.username == "alice"
        assert user.password_hash == "hashed"

    def test_none_for_unknown(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        assert repo.find_user_by_username("nobody") is None


class TestGetUserWithTotpSecret:
    def test_returns_secret(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db, totp_secret="ABC123")

        user = repo.get_user_with_totp_secret(user_id)
        assert user is not None
        assert user.totp_secret == "ABC123"


class TestTotpSecretLifecycle:
    def test_set_then_get(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)
        assert repo.get_totp_secret(user_id) is None

        repo.set_totp_secret(user_id, "SECRET")
        assert repo.get_totp_secret(user_id) == "SECRET"

    def test_set_enabled(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db, totp_secret="SECRET")
        repo.set_totp_enabled(user_id)

        user = repo.get_user_with_totp_secret(user_id)
        assert user is not None
        assert user.totp_enabled is True

    def test_clear_totp(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db, totp_secret="SECRET", totp_enabled=1)
        repo.clear_totp(user_id)

        user = repo.get_user_with_totp_secret(user_id)
        assert user is not None
        assert user.totp_enabled is False
        assert user.totp_secret is None


class TestGetPasswordAndTotp:
    def test_returns_expected_fields(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db, totp_secret="SECRET", totp_enabled=1)

        creds = repo.get_password_and_totp(user_id)
        assert creds is not None
        assert creds.password_hash == "hashed"
        assert creds.totp_secret == "SECRET"
        assert creds.totp_enabled is True

    def test_none_for_unknown_user(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        assert repo.get_password_and_totp(99999) is None


class TestUpdateLocaleAndPassword:
    def test_update_locale(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)
        repo.update_locale(user_id, "pt-BR")

        summary = repo.get_user_summary(user_id)
        assert summary is not None
        assert summary.locale == "pt-BR"

    def test_update_accent(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)
        repo.update_accent(user_id, "ocean")

        summary = repo.get_user_summary(user_id)
        assert summary is not None
        assert summary.accent == "ocean"

    def test_accent_defaults_to_sky_for_a_row_that_never_set_one(self, test_db):
        """Migration 0026 backfills every existing user with 'sky' rather than
        NULL, so the frontend never has to treat "unset" as a third state."""
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)

        summary = repo.get_user_summary(user_id)
        assert summary is not None
        assert summary.accent == "sky"

    def test_accent_is_carried_by_the_login_lookup_too(self, test_db):
        """Login builds its own UserSummary from find_user_by_username rather
        than from get_user_summary; a column missing there means the accent is
        correct on /me and wrong for the whole first page load after login."""
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db, username="alice")
        repo.update_accent(user_id, "dusk")

        user = repo.find_user_by_username("alice")
        assert user is not None
        assert user.accent == "dusk"

    def test_update_password_hash(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)
        repo.update_password_hash(user_id, "new-hash")

        creds = repo.get_password_and_totp(user_id)
        assert creds is not None
        assert creds.password_hash == "new-hash"


class TestCreateAdminUser:
    def test_creates_and_adopts_orphan_data(self, test_db):
        import sqlite3

        from backend.auth.repository import AuthRepository

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO trips (id, name, created_at, updated_at) VALUES ('t1', 'Orphan Trip', datetime('now'), datetime('now'))"
        )
        conn.commit()
        conn.close()

        repo = AuthRepository()
        user_id = repo.create_admin_user("admin", "hashed-pw", None)

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT user_id FROM trips WHERE id = 't1'").fetchone()
        conn.close()
        assert row["user_id"] == user_id


class TestTotpAttempts:
    def test_no_failures_initially(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)
        assert repo.count_recent_totp_failures(user_id, 15) == 0

    def test_counts_recent_failures(self, test_db):
        from backend.auth.repository import AuthRepository

        repo = AuthRepository()
        user_id = _seed_user(test_db)
        repo.record_totp_attempt(user_id, False)
        repo.record_totp_attempt(user_id, False)
        repo.record_totp_attempt(user_id, True)

        assert repo.count_recent_totp_failures(user_id, 15) == 2
