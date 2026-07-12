"""Tests for backend.auth.twofa_service (2FA setup/enable/disable/verify)."""

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


class TestVerify2fa:
    def test_no_pending_token(self, test_db):
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        with pytest.raises(AuthError) as exc_info:
            service.verify_2fa(None, "123456", "1.2.3.4")
        assert exc_info.value.status_code == 401

    def test_invalid_code_rejected(self, test_db):
        from backend.auth.session import create_pending_2fa_cookie
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db, totp_enabled=1, totp_secret=pyotp.random_base32())
        pending = create_pending_2fa_cookie(user_id)

        with pytest.raises(AuthError) as exc_info:
            service.verify_2fa(pending, "000000", "1.2.3.4")
        assert exc_info.value.status_code == 401

    def test_valid_code_returns_session(self, test_db):
        from backend.auth.session import create_pending_2fa_cookie
        from backend.auth.twofa_service import TwoFAService

        service = TwoFAService()
        secret = pyotp.random_base32()
        user_id = _seed_user(test_db, totp_enabled=1, totp_secret=secret)
        pending = create_pending_2fa_cookie(user_id)
        code = pyotp.TOTP(secret).now()

        summary, token = service.verify_2fa(pending, code, "1.2.3.4")
        assert summary.id == user_id
        assert token

    def test_totp_lockout_after_repeated_failures(self, test_db):
        from backend.auth.session import create_pending_2fa_cookie
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db, totp_enabled=1, totp_secret=pyotp.random_base32())

        for _ in range(5):
            pending = create_pending_2fa_cookie(user_id)
            with pytest.raises(AuthError):
                service.verify_2fa(pending, "000000", "1.2.3.4")

        pending = create_pending_2fa_cookie(user_id)
        with pytest.raises(AuthError) as exc_info:
            service.verify_2fa(pending, "000000", "1.2.3.4")
        assert exc_info.value.status_code == 429


class TestTwoFaSetupEnableDisable:
    def test_setup_generates_secret(self, test_db):
        from backend.auth.twofa_service import TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db)
        user = {"id": user_id, "username": "alice", "totp_enabled": False}

        result = service.setup_2fa(user)
        assert result.secret
        assert "otpauth://" in result.uri

    def test_setup_rejected_when_already_enabled(self, test_db):
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db)
        user = {"id": user_id, "username": "alice", "totp_enabled": True}
        with pytest.raises(AuthError):
            service.setup_2fa(user)

    def test_enable_requires_setup_first(self, test_db):
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db)
        with pytest.raises(AuthError):
            service.enable_2fa(user_id, "123456")

    def test_enable_with_valid_code(self, test_db):
        from backend.auth.twofa_service import TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db)
        user = {"id": user_id, "username": "alice", "totp_enabled": False}
        setup_result = service.setup_2fa(user)

        code = pyotp.TOTP(setup_result.secret).now()
        service.enable_2fa(user_id, code)  # should not raise

    def test_disable_requires_code_or_password(self, test_db):
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db)
        with pytest.raises(AuthError):
            service.disable_2fa(user_id, None, None)

    def test_disable_with_correct_password(self, test_db):
        from backend.auth.twofa_service import TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db, totp_enabled=1, totp_secret=pyotp.random_base32())
        service.disable_2fa(user_id, None, "password123")  # should not raise

    def test_disable_with_wrong_credentials_rejected(self, test_db):
        from backend.auth.twofa_service import AuthError, TwoFAService

        service = TwoFAService()
        user_id = _seed_user(test_db, totp_enabled=1, totp_secret=pyotp.random_base32())
        with pytest.raises(AuthError):
            service.disable_2fa(user_id, "000000", "wrongpassword")
