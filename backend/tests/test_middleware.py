"""Tests for backend.middleware (FirstRunMiddleware + security headers)."""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def _make_app(test_db):
    """Build a minimal FastAPI app with FirstRunMiddleware and the auth/flights routers."""
    from backend.middleware import FirstRunMiddleware
    from backend.routes import airports, auth, flights, settings, sync, trips, users

    app = FastAPI()
    app.add_middleware(FirstRunMiddleware)  # type: ignore[arg-type]
    app.include_router(auth.router)
    app.include_router(flights.router)
    app.include_router(trips.router)
    app.include_router(sync.router)
    app.include_router(airports.router)
    app.include_router(users.router)
    app.include_router(settings.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/static/index.html")
    def static():
        return JSONResponse({"page": "index"})

    return app


class TestFirstRunMiddleware:
    def test_setup_allowed_before_users_exist(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            r = c.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        assert r.status_code == 200

    def test_login_allowed_before_users_exist(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            r = c.post("/api/auth/login", json={"username": "x", "password": "y"})
        # Login fails with 401 (wrong creds), but middleware let it through (not 503)
        assert r.status_code != 503

    def test_me_returns_503_from_route_before_setup(self, test_db):
        """The /me route itself returns 503 before any users exist (route-level, not middleware)."""
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            r = c.get("/api/auth/me")
        # 503 is expected here — comes from the route handler, not the FirstRunMiddleware
        assert r.status_code == 503
        assert r.json().get("setup_required") is True

    def test_protected_api_blocked_before_setup(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            r = c.get("/api/flights")
        assert r.status_code == 503
        data = r.json()
        assert data["setup_required"] is True

    def test_protected_api_accessible_after_setup(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            c.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
            r = c.get("/api/flights")
        # Should not be 503 anymore (may be 401 without auth cookie)
        assert r.status_code != 503

    def test_non_api_path_not_blocked(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            r = c.get("/static/index.html")
        assert r.status_code != 503


class TestSecurityHeaders:
    def test_security_headers_present(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            # After setup so we get a real response
            c.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
            r = c.get("/api/auth/me")

        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert "strict-origin-when-cross-origin" in r.headers.get("Referrer-Policy", "")
        assert "Permissions-Policy" in r.headers
        assert "Content-Security-Policy" in r.headers
        assert "max-age=31536000" in r.headers.get("Strict-Transport-Security", "")

    def test_csp_header_value(self, test_db):
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            c.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
            r = c.get("/api/auth/me")

        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_security_headers_on_404_response(self, test_db):
        """Security headers are added to non-blocked responses (404 from a missing route)."""
        app = _make_app(test_db)
        with TestClient(app, base_url="https://testserver") as c:
            c.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
            r = c.get("/api/does-not-exist")

        # 404 or other response — but headers should be present because it went through call_next
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
