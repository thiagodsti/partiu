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

    def test_me_carries_carto_api_key(self, auth_client, monkeypatch):
        """The trip map reads its CARTO key off /auth/me — the image is built
        before the deployer has a key, so it cannot be baked in at build time."""
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "CARTO_API_KEY", "carto-test-key")
        data = auth_client.get("/api/auth/me").json()
        assert data["carto_api_key"] == "carto-test-key"

    def test_me_carto_api_key_empty_when_unset(self, auth_client, monkeypatch):
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "CARTO_API_KEY", "")
        data = auth_client.get("/api/auth/me").json()
        assert data["carto_api_key"] == ""

    def test_me_reports_demo_mode(self, auth_client, monkeypatch):
        """The banner has to be permanent on a demo instance, so the frontend
        needs to know it is on one."""
        import backend.config as cfg_module

        assert auth_client.get("/api/auth/me").json()["demo"] is False
        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)
        assert auth_client.get("/api/auth/me").json()["demo"] is True


# ---------------------------------------------------------------------------
# /api/auth/public-config
# ---------------------------------------------------------------------------


class TestPublicConfig:
    """The login page reads this before anyone has signed in, so it must answer
    unauthenticated — and must say nothing at all unless DEMO_MODE is on."""

    def test_says_nothing_by_default(self, client):
        r = client.get("/api/auth/public-config")
        assert r.status_code == 200
        data = r.json()
        assert data == {"demo": False, "demo_username": "", "demo_password": ""}

    def test_publishes_the_demo_credentials_when_demo_mode_is_on(self, client, monkeypatch):
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)
        monkeypatch.setattr(cfg_module.settings, "DEMO_USERNAME", "demo")
        monkeypatch.setattr(cfg_module.settings, "DEMO_PASSWORD", "demo1234")
        data = client.get("/api/auth/public-config").json()
        assert data == {"demo": True, "demo_username": "demo", "demo_password": "demo1234"}

    def test_a_configured_password_never_leaks_with_demo_mode_off(self, client, monkeypatch):
        """The credentials being set is not consent to publish them."""
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", False)
        monkeypatch.setattr(cfg_module.settings, "DEMO_PASSWORD", "demo1234")
        body = client.get("/api/auth/public-config").text
        assert "demo1234" not in body

    def test_reachable_before_setup(self, client):
        """FirstRunMiddleware 503s every other /api/ path until an account
        exists; this one is on the allowlist beside /login and /me."""
        r = client.get("/api/auth/public-config")
        assert r.status_code == 200

    def test_requires_no_session(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        assert client.get("/api/auth/public-config").status_code == 200


class TestDemoLoginIsNotThrottled:
    """A demo instance is a crowd arriving with one published username, often
    behind one proxy address. The per-IP defences read that as an attack."""

    @pytest.fixture(autouse=True)
    def _clean_lockout_state(self):
        """The failure counter lives on a module-level singleton and its window
        is ten minutes, so a test that deliberately trips the lockout would 429
        every later test that signs in."""
        from backend.auth import auth_service

        auth_service._login_failures.clear()
        yield
        auth_service._login_failures.clear()

    def test_the_per_ip_lockout_is_off_in_demo_mode(self, client, monkeypatch):
        import backend.config as cfg_module

        client.post("/api/auth/setup", json={"username": "demo", "password": "demo1234"})
        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)

        # Well past _LOGIN_LOCKOUT_THRESHOLD: every one of these is a wrong
        # password, and the next real visitor must still get in.
        for _ in range(12):
            assert (
                client.post(
                    "/api/auth/login", json={"username": "demo", "password": "wrong"}
                ).status_code
                == 401
            )
        r = client.post("/api/auth/login", json={"username": "demo", "password": "demo1234"})
        assert r.status_code == 200

    def test_the_lockout_still_applies_on_an_ordinary_install(self, client, monkeypatch):
        import backend.config as cfg_module

        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", False)

        codes = [
            client.post(
                "/api/auth/login", json={"username": "admin", "password": "wrong"}
            ).status_code
            for _ in range(8)
        ]
        assert 429 in codes

    def test_the_route_ceiling_is_raised_not_removed(self, monkeypatch):
        """Rate limiting is stubbed out in the test suite, so the decorator's
        callable is checked directly. It must still return a real limit in demo
        mode — a crowd cannot reach 120/minute, a script can."""
        import backend.config as cfg_module
        from backend.auth.routes import _login_rate_limit

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", False)
        assert _login_rate_limit() == "5/minute"
        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)
        assert _login_rate_limit() == "120/minute"


class TestDemoLocksTheSharedCredentials:
    """One visitor must not be able to lock the rest of the world out of the
    demo account — both of these are one-way doors without shell access."""

    def test_enabling_2fa_is_refused(self, auth_client, monkeypatch):
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)
        r = auth_client.post("/api/auth/2fa/enable", json={"code": "123456"})
        assert r.status_code == 403
        assert auth_client.get("/api/auth/me").json()["totp_enabled"] is False

    def test_changing_the_password_is_refused(self, auth_client, monkeypatch):
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)
        r = auth_client.post(
            "/api/auth/change-password",
            json={"current_password": "password123", "new_password": "somethingelse"},
        )
        assert r.status_code == 403
        # The published password still works, which is the whole point.
        auth_client.cookies.clear()
        login = auth_client.post(
            "/api/auth/login", json={"username": "admin", "password": "password123"}
        )
        assert login.status_code == 200

    def test_disabling_2fa_is_still_allowed(self, auth_client, monkeypatch):
        """The escape hatch stays open: on an account whose password is public,
        turning 2FA off gives an attacker nothing and un-bricks the demo."""
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", True)
        r = auth_client.post("/api/auth/2fa/disable", json={"password": "password123"})
        assert r.status_code != 403

    def test_both_are_allowed_on_an_ordinary_install(self, auth_client, monkeypatch):
        import backend.config as cfg_module

        monkeypatch.setattr(cfg_module.settings, "DEMO_MODE", False)
        # Wrong TOTP code and wrong password respectively — the point is that
        # neither is turned away with a 403 before it is even considered.
        assert auth_client.post("/api/auth/2fa/enable", json={"code": "000000"}).status_code != 403
        assert (
            auth_client.post(
                "/api/auth/change-password",
                json={"current_password": "password123", "new_password": "newpassword1"},
            ).status_code
            != 403
        )


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
        """Set up and enable 2FA, return the secret.

        Enabling 2FA revokes all existing sessions, so we re-authenticate
        through the 2FA flow to keep auth_client usable after this call.
        """
        import pyotp

        r = auth_client.get("/api/auth/2fa/setup")
        assert r.status_code == 200
        secret = r.json()["secret"]
        code = pyotp.TOTP(secret).now()
        r2 = auth_client.post("/api/auth/2fa/enable", json={"code": code})
        assert r2.status_code == 200

        # Session was revoked — re-authenticate through 2FA
        r3 = auth_client.post(
            "/api/auth/login", json={"username": "admin", "password": "password123"}
        )
        assert r3.json().get("requires_2fa") is True
        code2 = pyotp.TOTP(secret).now()
        r4 = auth_client.post("/api/auth/2fa/verify", json={"code": code2})
        assert r4.status_code == 200

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


# ---------------------------------------------------------------------------
# /api/auth/me PATCH — locale preference
# ---------------------------------------------------------------------------


class TestUpdateMe:
    def test_me_returns_locale(self, auth_client):
        r = auth_client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["locale"] == "en"

    def test_login_returns_locale(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        assert r.status_code == 200
        assert r.json()["locale"] == "en"

    def test_update_locale(self, auth_client):
        r = auth_client.patch("/api/auth/me", json={"locale": "pt-BR"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r2 = auth_client.get("/api/auth/me")
        assert r2.json()["locale"] == "pt-BR"

    def test_locale_persists_after_relogin(self, auth_client, api_app):
        auth_client.patch("/api/auth/me", json={"locale": "pt-BR"})
        auth_client.post("/api/auth/logout")

        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            r = c.post("/api/auth/login", json={"username": "admin", "password": "password123"})
            assert r.json()["locale"] == "pt-BR"

    def test_update_locale_invalid(self, auth_client):
        r = auth_client.patch("/api/auth/me", json={"locale": "fr"})
        assert r.status_code == 422

    def test_update_locale_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.patch("/api/auth/me", json={"locale": "pt-BR"})
        assert r.status_code == 401

    def test_me_returns_accent(self, auth_client):
        r = auth_client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["accent"] == "sky"

    def test_update_accent(self, auth_client):
        r = auth_client.patch("/api/auth/me", json={"accent": "ocean"})
        assert r.status_code == 200

        r2 = auth_client.get("/api/auth/me")
        assert r2.json()["accent"] == "ocean"

    def test_accent_follows_the_user_to_another_browser(self, auth_client, api_app):
        """The whole point of moving this off localStorage: a fresh client with
        no storage of its own gets the accent back from the session alone."""
        auth_client.patch("/api/auth/me", json={"accent": "dusk"})
        auth_client.post("/api/auth/logout")

        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            r = c.post("/api/auth/login", json={"username": "admin", "password": "password123"})
            assert r.json()["accent"] == "dusk"

    def test_update_accent_invalid(self, auth_client):
        r = auth_client.patch("/api/auth/me", json={"accent": "chartreuse"})
        assert r.status_code == 422

    def test_accent_and_locale_are_independent_over_the_api(self, auth_client):
        auth_client.patch("/api/auth/me", json={"locale": "pt-BR"})
        auth_client.patch("/api/auth/me", json={"accent": "graphite"})

        r = auth_client.get("/api/auth/me")
        assert r.json()["locale"] == "pt-BR"
        assert r.json()["accent"] == "graphite"
