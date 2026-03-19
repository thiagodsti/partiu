"""Unit tests for backend.auth helper functions."""

import pytest


class TestPasswordHashing:
    def test_hash_password_is_not_plaintext(self):
        from backend.auth import hash_password

        hashed = hash_password("mypassword")
        assert hashed != "mypassword"
        assert len(hashed) > 20

    def test_verify_password_correct(self):
        from backend.auth import hash_password, verify_password

        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_verify_password_wrong(self):
        from backend.auth import hash_password, verify_password

        hashed = hash_password("mypassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_bad_hash(self):
        from backend.auth import verify_password

        assert verify_password("password", "not-a-valid-hash") is False

    def test_two_hashes_differ(self):
        from backend.auth import hash_password

        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # bcrypt uses random salt


class TestSessionCookies:
    def test_create_and_decode_session(self, test_db):
        from backend.auth import create_session_cookie, decode_session_cookie, hash_password
        from backend.database import db_write

        # Create a user
        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                ("testuser", hash_password("password")),
            )
            user_id = cur.lastrowid

        token = create_session_cookie(user_id)
        assert token is not None
        assert isinstance(token, str)

        decoded_uid = decode_session_cookie(token)
        assert decoded_uid == user_id

    def test_decode_invalid_token(self, test_db):
        from backend.auth import decode_session_cookie

        assert decode_session_cookie("not-a-valid-token") is None

    def test_decode_empty_token(self, test_db):
        from backend.auth import decode_session_cookie

        assert decode_session_cookie("") is None

    def test_revoke_session(self, test_db):
        from backend.auth import (
            create_session_cookie,
            decode_session_cookie,
            hash_password,
            revoke_session_cookie,
        )
        from backend.database import db_write

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                ("testuser", hash_password("password")),
            )
            user_id = cur.lastrowid

        token = create_session_cookie(user_id)
        assert decode_session_cookie(token) == user_id

        revoke_session_cookie(token)
        assert decode_session_cookie(token) is None

    def test_revoke_invalid_token_no_error(self, test_db):
        from backend.auth import revoke_session_cookie

        revoke_session_cookie("garbage-token")  # should not raise


class TestPending2FAToken:
    def test_create_and_decode(self, test_db):
        from backend.auth import create_pending_2fa_cookie, decode_pending_2fa_cookie

        token = create_pending_2fa_cookie(42)
        assert decode_pending_2fa_cookie(token) == 42

    def test_decode_invalid(self, test_db):
        from backend.auth import decode_pending_2fa_cookie

        assert decode_pending_2fa_cookie("garbage") is None


class TestHasAnyUsers:
    def test_no_users(self, test_db):
        from backend.auth import has_any_users

        assert has_any_users() is False

    def test_with_user(self, test_db):
        from backend.auth import has_any_users, hash_password
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                ("admin", hash_password("password")),
            )
        assert has_any_users() is True


class TestGetUserImapSettings:
    def test_defaults_when_empty(self):
        from backend.auth import get_user_imap_settings

        result = get_user_imap_settings({})
        assert result["imap_host"] == "imap.gmail.com"
        assert result["imap_port"] == 993
        assert result["gmail_address"] is None
        assert result["gmail_app_password"] is None

    def test_custom_values(self):
        from backend.auth import get_user_imap_settings

        user = {
            "gmail_address": "me@gmail.com",
            "gmail_app_password": "secret",
            "imap_host": "imap.custom.com",
            "imap_port": 143,
        }
        result = get_user_imap_settings(user)
        assert result["gmail_address"] == "me@gmail.com"
        assert result["imap_host"] == "imap.custom.com"
        assert result["imap_port"] == 143


class TestValidateSecretKey:
    def test_validate_ok(self, test_db):
        from backend.auth import validate_secret_key

        validate_secret_key()  # should not raise with SECRET_KEY set in conftest
