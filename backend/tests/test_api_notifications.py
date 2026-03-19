"""Tests for /api/notifications/* endpoints."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest


@pytest.fixture
def notif_app(test_db):
    from fastapi import FastAPI

    from backend.routes import auth as auth_routes
    from backend.routes import notifications as notif_routes

    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(notif_routes.router)
    return app


@pytest.fixture
def notif_client(notif_app):
    from fastapi.testclient import TestClient

    with TestClient(notif_app, raise_server_exceptions=True, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def auth_notif_client(notif_app):
    from fastapi.testclient import TestClient

    with TestClient(notif_app, raise_server_exceptions=True, base_url="https://testserver") as c:
        c.post("/api/auth/setup", json={"username": "admin", "password": "pass1234"})
        yield c


class TestVapidAdmin:
    def test_vapid_status_not_configured(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        r = auth_notif_client.get("/api/notifications/vapid/status")
        assert r.status_code == 200
        assert r.json()["configured"] is False
        assert r.json()["source"] == "none"

    def test_vapid_status_configured_from_env(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        r = auth_notif_client.get("/api/notifications/vapid/status")
        assert r.status_code == 200
        assert r.json()["configured"] is True
        assert r.json()["source"] == "env"

    def test_generate_vapid_keys(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        r = auth_notif_client.post("/api/notifications/vapid/generate")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["source"] == "database"
        assert len(data["public_key"]) > 10

    def test_generate_vapid_makes_status_configured(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        auth_notif_client.post("/api/notifications/vapid/generate")

        r = auth_notif_client.get("/api/notifications/vapid/status")
        assert r.json()["configured"] is True
        assert r.json()["source"] == "database"

    def test_vapid_status_requires_admin(self, notif_client):
        r = notif_client.get("/api/notifications/vapid/status")
        assert r.status_code == 401

    def test_generate_requires_admin(self, notif_client):
        r = notif_client.post("/api/notifications/vapid/generate")
        assert r.status_code == 401


class TestVapidPublicKey:
    def test_returns_key_when_configured(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fakepublickey123")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fakeprivatekey123")
        r = auth_notif_client.get("/api/notifications/vapid-public-key")
        assert r.status_code == 200
        assert r.json()["public_key"] == "fakepublickey123"

    def test_503_when_not_configured(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        r = auth_notif_client.get("/api/notifications/vapid-public-key")
        assert r.status_code == 503

    def test_returns_503_to_unauthed_when_not_configured(self, notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        r = notif_client.get("/api/notifications/vapid-public-key")
        assert r.status_code == 503


class TestSubscribe:
    def test_saves_subscription(self, auth_notif_client):
        payload = {
            "subscription": {
                "endpoint": "https://fcm.googleapis.com/test",
                "keys": {"p256dh": "abc", "auth": "xyz"},
            }
        }
        r = auth_notif_client.post("/api/notifications/subscribe", json=payload)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_missing_endpoint_returns_422(self, auth_notif_client):
        r = auth_notif_client.post("/api/notifications/subscribe", json={"subscription": {}})
        assert r.status_code == 422

    def test_requires_auth(self, notif_client):
        r = notif_client.post(
            "/api/notifications/subscribe", json={"subscription": {"endpoint": "x", "keys": {}}}
        )
        assert r.status_code == 401


class TestUnsubscribe:
    def test_removes_subscription(self, auth_notif_client):
        # First subscribe
        sub = {"endpoint": "https://fcm.googleapis.com/del", "keys": {"p256dh": "p", "auth": "a"}}
        auth_notif_client.post("/api/notifications/subscribe", json={"subscription": sub})

        # Then unsubscribe
        r = auth_notif_client.request(
            "DELETE",
            "/api/notifications/subscribe",
            json={"endpoint": "https://fcm.googleapis.com/del"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_missing_endpoint_returns_422(self, auth_notif_client):
        r = auth_notif_client.request("DELETE", "/api/notifications/subscribe", json={})
        assert r.status_code == 422


class TestPreferences:
    def test_get_defaults(self, auth_notif_client):
        r = auth_notif_client.get("/api/notifications/preferences")
        assert r.status_code == 200
        data = r.json()
        assert data["flight_reminder"] is True
        assert data["checkin_reminder"] is True
        assert data["trip_reminder"] is True

    def test_update_preferences(self, auth_notif_client):
        r = auth_notif_client.post(
            "/api/notifications/preferences",
            json={"flight_reminder": False, "checkin_reminder": True},
        )
        assert r.status_code == 200

        r2 = auth_notif_client.get("/api/notifications/preferences")
        assert r2.json()["flight_reminder"] is False
        assert r2.json()["checkin_reminder"] is True

    def test_update_invalid_fields_rejected(self, auth_notif_client):
        r = auth_notif_client.post(
            "/api/notifications/preferences",
            json={"invalid_field": True},
        )
        assert r.status_code == 422

    def test_requires_auth(self, notif_client):
        r = notif_client.get("/api/notifications/preferences")
        assert r.status_code == 401


class TestTestPush:
    def test_503_when_vapid_not_configured(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        r = auth_notif_client.post("/api/notifications/test")
        assert r.status_code == 503

    def test_400_when_no_subscriptions(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        r = auth_notif_client.post("/api/notifications/test")
        assert r.status_code == 400

    def test_sends_push_when_subscribed(self, auth_notif_client, monkeypatch):
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")
        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")

        # Add a subscription
        sub = {"endpoint": "https://fcm.example.com/test", "keys": {"p256dh": "p", "auth": "a"}}
        auth_notif_client.post("/api/notifications/subscribe", json={"subscription": sub})

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            r = auth_notif_client.post("/api/notifications/test")

        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["sent"] == 1
