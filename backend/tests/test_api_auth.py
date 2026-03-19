"""Tests for /api/auth routes."""

import pytest

# ---------------------------------------------------------------------------
# /api/auth/setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_setup_creates_admin(self, client):
        r = client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "admin"
        assert data["is_admin"] is True
        assert data["totp_enabled"] is False

    def test_setup_with_smtp_address(self, client):
        r = client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "password": "password123",
                "smtp_recipient_address": "admin@example.com",
            },
        )
        assert r.status_code == 200
        assert r.json()["smtp_recipient_address"] == "admin@example.com"

    def test_setup_sets_session_cookie(self, client):
        r = client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        assert r.status_code == 200
        assert "session" in client.cookies

    def test_setup_already_done_returns_409(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        r = client.post("/api/auth/setup", json={"username": "admin2", "password": "password123"})
        assert r.status_code == 409

    def test_setup_username_too_short(self, client):
        r = client.post("/api/auth/setup", json={"username": "a", "password": "password123"})
        assert r.status_code == 400

    def test_setup_password_too_short(self, client):
        r = client.post("/api/auth/setup", json={"username": "admin", "password": "short"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# /api/auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_success(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        # Clear the session cookie set by setup
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "admin"
        assert data["is_admin"] is True

    def test_login_wrong_password(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    def test_login_unknown_user(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"username": "nobody", "password": "password123"})
        assert r.status_code == 401

    def test_login_sets_session_cookie(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        assert "session" in client.cookies


# ---------------------------------------------------------------------------
# /api/auth/me
# ---------------------------------------------------------------------------


class TestMe:
    def test_me_no_users_setup_required(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 503
        assert r.json()["setup_required"] is True

    def test_me_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_authenticated(self, auth_client):
        r = auth_client.get("/api/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "admin"
        assert data["is_admin"] is True
        assert "totp_enabled" in data


# ---------------------------------------------------------------------------
# /api/auth/logout
# ---------------------------------------------------------------------------


class TestLogout:
    def test_logout_clears_session(self, auth_client):
        r = auth_client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_logout_revokes_session(self, auth_client):
        auth_client.post("/api/auth/logout")
        # After logout the session is revoked — me returns 401
        r = auth_client.get("/api/auth/me")
        assert r.status_code == 401

    def test_logout_without_cookie_ok(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/auth/logout")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# /api/auth/change-password
# ---------------------------------------------------------------------------


class TestChangePassword:
    def test_change_password_success(self, auth_client):
        r = auth_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_change_password_wrong_current(self, auth_client):
        r = auth_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "wrongpass",
                "new_password": "newpassword456",
            },
        )
        assert r.status_code == 400

    def test_change_password_new_too_short(self, auth_client):
        r = auth_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "short",
            },
        )
        assert r.status_code == 400

    def test_change_password_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
        )
        assert r.status_code == 401

    def test_change_password_then_login_with_new(self, auth_client, api_app):
        auth_client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "newpassword456",
            },
        )
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            r = c.post("/api/auth/login", json={"username": "admin", "password": "newpassword456"})
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# /api/auth/2fa
# ---------------------------------------------------------------------------


class TestTwoFA:
    def _setup_2fa(self, auth_client):
        """Set up and enable 2FA, return the secret."""
        import pyotp

        r = auth_client.get("/api/auth/2fa/setup")
        assert r.status_code == 200
        secret = r.json()["secret"]
        code = pyotp.TOTP(secret).now()
        r2 = auth_client.post("/api/auth/2fa/enable", json={"code": code})
        assert r2.status_code == 200
        return secret

    def test_2fa_setup_returns_secret_and_uri(self, auth_client):
        r = auth_client.get("/api/auth/2fa/setup")
        assert r.status_code == 200
        data = r.json()
        assert "secret" in data
        assert "uri" in data
        assert "otpauth://" in data["uri"]

    def test_2fa_enable_then_verify(self, auth_client, api_app):
        import pyotp

        secret = self._setup_2fa(auth_client)

        # Now login should require 2FA
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            r = c.post("/api/auth/login", json={"username": "admin", "password": "password123"})
            assert r.status_code == 200
            assert r.json().get("requires_2fa") is True

            # Verify with correct code
            code = pyotp.TOTP(secret).now()
            r2 = c.post("/api/auth/2fa/verify", json={"code": code})
            assert r2.status_code == 200
            assert "session" in c.cookies

    def test_2fa_verify_wrong_code(self, auth_client, api_app):
        self._setup_2fa(auth_client)
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "admin", "password": "password123"})
            r = c.post("/api/auth/2fa/verify", json={"code": "000000"})
            assert r.status_code == 401

    def test_2fa_verify_no_pending_session(self, auth_client):
        r = auth_client.post("/api/auth/2fa/verify", json={"code": "123456"})
        assert r.status_code == 401

    def test_2fa_setup_already_enabled(self, auth_client):
        self._setup_2fa(auth_client)
        r = auth_client.get("/api/auth/2fa/setup")
        assert r.status_code == 400

    def test_2fa_disable_with_password(self, auth_client):
        self._setup_2fa(auth_client)
        r = auth_client.post("/api/auth/2fa/disable", json={"password": "password123"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_2fa_disable_with_totp(self, auth_client):
        import pyotp

        secret = self._setup_2fa(auth_client)
        code = pyotp.TOTP(secret).now()
        r = auth_client.post("/api/auth/2fa/disable", json={"code": code})
        assert r.status_code == 200

    def test_2fa_disable_no_credentials(self, auth_client):
        r = auth_client.post("/api/auth/2fa/disable", json={})
        assert r.status_code == 400

    def test_2fa_disable_wrong_password(self, auth_client):
        self._setup_2fa(auth_client)
        r = auth_client.post("/api/auth/2fa/disable", json={"password": "wrongpassword"})
        assert r.status_code == 400
