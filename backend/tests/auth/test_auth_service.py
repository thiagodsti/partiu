"""Tests for backend.auth.service (setup/login/logout/me/change-password use
cases). 2FA setup/enable/disable/verify tests live in test_twofa_service.py."""

import itertools
from datetime import UTC, datetime

import pyotp
import pytest

_user_counter = itertools.count(1)


def _seed_user(db_path: str, **overrides) -> int:
    import sqlite3

    from backend.auth.session import hash_password

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = overrides.pop("username", f"testuser{next(_user_counter)}")
    password_hash = overrides.pop("password_hash", hash_password("password123"))
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, password_hash, 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if overrides:
        set_clause = ", ".join(f"{k} = ?" for k in overrides)
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*overrides.values(), user_id))
        conn.commit()
    conn.close()
    return user_id


class TestSetup:
    def test_rejects_when_users_exist(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        _seed_user(test_db)
        with pytest.raises(AuthError) as exc_info:
            service.setup("newadmin", "password123", None)
        assert exc_info.value.status_code == 409

    def test_rejects_short_username(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        with pytest.raises(AuthError) as exc_info:
            service.setup("abc", "password123", None)
        assert exc_info.value.status_code == 400

    def test_creates_admin_and_returns_session_token(self, test_db):
        from backend.auth.service import AuthService

        service = AuthService()
        summary, token = service.setup("Admin", "password123", None)
        assert summary.username == "admin"
        assert summary.is_admin is True
        assert token


class TestLogin:
    def test_rejects_unknown_user(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        with pytest.raises(AuthError) as exc_info:
            service.login("nobody", "password123", "1.2.3.4")
        assert exc_info.value.status_code == 401

    def test_rejects_wrong_password(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        _seed_user(test_db, username="alice")
        with pytest.raises(AuthError):
            service.login("alice", "wrongpassword", "1.2.3.4")

    def test_succeeds_without_2fa(self, test_db):
        from backend.auth.service import AuthService

        service = AuthService()
        _seed_user(test_db, username="alice")
        result = service.login("alice", "password123", "1.2.3.4")
        assert result.requires_2fa is False
        assert result.session_token

    def test_requires_2fa_when_enabled(self, test_db):
        from backend.auth.service import AuthService

        service = AuthService()
        _seed_user(test_db, username="alice", totp_enabled=1, totp_secret="SECRET")
        result = service.login("alice", "password123", "1.2.3.4")
        assert result.requires_2fa is True
        assert result.pending_token

    def test_lockout_after_repeated_failures(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        _seed_user(test_db, username="alice")
        for _ in range(5):
            with pytest.raises(AuthError):
                service.login("alice", "wrongpassword", "9.9.9.9")

        with pytest.raises(AuthError) as exc_info:
            service.login("alice", "password123", "9.9.9.9")  # correct password, still locked out
        assert exc_info.value.status_code == 429


class TestGetMeAndUpdateMe:
    def test_no_token_unauthenticated(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        with pytest.raises(AuthError) as exc_info:
            service.get_me(None)
        assert exc_info.value.status_code == 401

    def test_valid_token_returns_summary(self, test_db):
        from backend.auth.service import AuthService
        from backend.auth.session import create_session_cookie

        service = AuthService()
        user_id = _seed_user(test_db, username="alice")
        token = create_session_cookie(user_id)

        summary = service.get_me(token)
        assert summary.username == "alice"

    def test_update_me_rejects_invalid_locale(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        with pytest.raises(AuthError) as exc_info:
            service.update_me(user_id, "xx-XX")
        assert exc_info.value.status_code == 422

    def test_update_me_sets_locale(self, test_db):
        from backend.auth.service import AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        service.update_me(user_id, "pt-BR")

        summary = service._repository.get_user_summary(user_id)
        assert summary is not None
        assert summary.locale == "pt-BR"

    def test_update_me_rejects_an_accent_the_stylesheet_has_no_block_for(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        with pytest.raises(AuthError) as exc_info:
            service.update_me(user_id, None, "chartreuse")
        assert exc_info.value.status_code == 422

    def test_update_me_sets_accent(self, test_db):
        from backend.auth.service import AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        service.update_me(user_id, None, "orchid")

        summary = service._repository.get_user_summary(user_id)
        assert summary is not None
        assert summary.accent == "orchid"

    def test_update_me_leaves_the_other_preference_alone(self, test_db):
        """Settings sends one field at a time, so a PATCH carrying only an
        accent must not reset the locale to its default."""
        from backend.auth.service import AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        service.update_me(user_id, "pt-BR", None)
        service.update_me(user_id, None, "ocean")

        summary = service._repository.get_user_summary(user_id)
        assert summary is not None
        assert summary.locale == "pt-BR"
        assert summary.accent == "ocean"


class TestChangePassword:
    def test_rejects_wrong_current_password(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        with pytest.raises(AuthError):
            service.change_password(user_id, "wrongpassword", "newpassword123", None)

    def test_rejects_short_new_password(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        user_id = _seed_user(test_db)
        with pytest.raises(AuthError):
            service.change_password(user_id, "password123", "short", None)

    def test_requires_totp_code_when_2fa_enabled(self, test_db):
        from backend.auth.service import AuthError, AuthService

        service = AuthService()
        user_id = _seed_user(test_db, totp_enabled=1, totp_secret=pyotp.random_base32())
        with pytest.raises(AuthError):
            service.change_password(user_id, "password123", "newpassword123", None)

    def test_succeeds_and_new_password_works(self, test_db):
        from backend.auth.service import AuthService
        from backend.auth.session import verify_password

        service = AuthService()
        user_id = _seed_user(test_db)
        service.change_password(user_id, "password123", "newpassword123", None)

        creds = service._repository.get_password_and_totp(user_id)
        assert creds is not None
        assert verify_password("newpassword123", creds.password_hash)
