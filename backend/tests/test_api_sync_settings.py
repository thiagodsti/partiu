"""Tests for /api/sync and /api/settings routes."""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Sync routes
# ---------------------------------------------------------------------------


class TestSyncStatus:
    def test_status_no_sync_yet(self, auth_client):
        r = auth_client.get("/api/sync/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "idle"
        assert data["last_synced_at"] is None
        assert "sync_interval_minutes" in data

    def test_status_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/sync/status")
        assert r.status_code == 401

    def test_status_after_sync_record(self, auth_client):
        from datetime import UTC, datetime

        from backend.database import db_write

        # Simulate a sync record
        r = auth_client.get("/api/users")
        user_id = r.json()[0]["id"]
        with db_write() as conn:
            conn.execute(
                "INSERT INTO email_sync_state (user_id, status, last_synced_at) VALUES (?, 'idle', ?)",
                (user_id, datetime.now(UTC).isoformat()),
            )
        r2 = auth_client.get("/api/sync/status")
        assert r2.status_code == 200
        assert r2.json()["last_synced_at"] is not None


class TestSyncNow:
    def test_sync_now_starts_background(self, auth_client):
        with patch("backend.sync_job.run_email_sync_for_user"):
            r = auth_client.post("/api/sync/now")
        assert r.status_code == 200
        assert r.json()["status"] == "started"

    def test_sync_now_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/sync/now")
        assert r.status_code == 401


class TestRegroup:
    def test_regroup_starts(self, auth_client):
        r = auth_client.post("/api/sync/regroup")
        assert r.status_code == 200
        assert r.json()["status"] == "started"

    def test_regroup_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/sync/regroup")
        assert r.status_code == 401


class TestResetAndSync:
    def test_reset_and_sync_starts(self, auth_client):
        with patch(
            "backend.sync_job.reset_auto_flights",
            return_value={"flights_deleted": 0, "trips_deleted": 0},
        ):
            with patch("backend.sync_job.run_email_sync_for_user"):
                r = auth_client.post("/api/sync/reset-and-sync")
        assert r.status_code == 200
        assert r.json()["status"] == "started"


# ---------------------------------------------------------------------------
# Settings routes
# ---------------------------------------------------------------------------


class TestGetSettings:
    def test_get_settings_returns_defaults(self, auth_client):
        r = auth_client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "gmail_address" in data
        assert "imap_host" in data
        assert "imap_port" in data
        assert data["imap_host"] == "imap.gmail.com"
        assert data["imap_port"] == 993

    def test_get_settings_admin_has_smtp_port(self, auth_client):
        r = auth_client.get("/api/settings")
        assert "smtp_server_port" in r.json()

    def test_get_settings_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/settings")
        assert r.status_code == 401

    def test_get_settings_gmail_password_masked(self, auth_client):
        # Update to set a password
        auth_client.post(
            "/api/settings",
            json={
                "gmail_address": "test@gmail.com",
                "gmail_app_password": "secret",
            },
        )
        r = auth_client.get("/api/settings")
        data = r.json()
        assert data["gmail_app_password_set"] is True
        assert "secret" not in str(data)


class TestUpdateSettings:
    def test_update_gmail_address(self, auth_client):
        r = auth_client.post("/api/settings", json={"gmail_address": "me@gmail.com"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        r2 = auth_client.get("/api/settings")
        assert r2.json()["gmail_address"] == "me@gmail.com"

    def test_update_imap_port(self, auth_client):
        r = auth_client.post("/api/settings", json={"imap_port": 993})
        assert r.status_code == 200

    def test_update_imap_port_invalid(self, auth_client):
        r = auth_client.post("/api/settings", json={"imap_port": 99999})
        assert r.status_code == 400

    def test_update_imap_host_localhost_rejected(self, auth_client):
        r = auth_client.post("/api/settings", json={"imap_host": "localhost"})
        assert r.status_code == 400

    def test_update_global_settings_as_admin(self, auth_client):
        r = auth_client.post("/api/settings", json={"sync_interval_minutes": 30})
        assert r.status_code == 200
        r2 = auth_client.get("/api/settings")
        assert r2.json()["sync_interval_minutes"] == 30

    def test_update_global_settings_non_admin_forbidden(self, auth_client, api_app):
        auth_client.post("/api/users", json={"username": "regular", "password": "password123"})
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "regular", "password": "password123"})
            r = c.post("/api/settings", json={"sync_interval_minutes": 30})
            assert r.status_code == 403

    def test_update_smtp_recipient_address(self, auth_client):
        r = auth_client.post("/api/settings", json={"smtp_recipient_address": "me@example.com"})
        assert r.status_code == 200

    def test_update_smtp_conflict(self, auth_client):
        # Create another user with that address
        auth_client.post("/api/users", json={"username": "bobby", "password": "password123"})
        # Give bobby an smtp address
        r_users = auth_client.get("/api/users")
        bob = next(u for u in r_users.json() if u["username"] == "bobby")
        auth_client.patch(
            f"/api/users/{bob['id']}", json={"smtp_recipient_address": "shared@example.com"}
        )
        # Try to set same address for admin
        r = auth_client.post("/api/settings", json={"smtp_recipient_address": "shared@example.com"})
        assert r.status_code == 409

    def test_update_multiple_global_settings(self, auth_client):
        r = auth_client.post(
            "/api/settings",
            json={
                "max_emails_per_sync": 100,
                "first_sync_days": 30,
                "smtp_server_enabled": False,
                "smtp_server_port": 2525,
                "smtp_domain": "mail.example.com",
            },
        )
        assert r.status_code == 200

    def test_update_no_fields_ok(self, auth_client):
        r = auth_client.post("/api/settings", json={})
        assert r.status_code == 200


class TestTestImap:
    def test_test_imap_missing_address(self, auth_client):
        r = auth_client.post("/api/settings/test-imap", json={})
        assert r.status_code == 400

    def test_test_imap_missing_password(self, auth_client):
        r = auth_client.post("/api/settings/test-imap", json={"gmail_address": "test@gmail.com"})
        assert r.status_code == 400

    def test_test_imap_localhost_rejected(self, auth_client):
        r = auth_client.post(
            "/api/settings/test-imap",
            json={
                "imap_host": "localhost",
                "gmail_address": "test@gmail.com",
                "gmail_app_password": "secret",
            },
        )
        assert r.status_code == 400

    def test_test_imap_connection_failure(self, auth_client):
        with patch("imaplib.IMAP4_SSL") as mock_imap:
            mock_imap.side_effect = OSError("Connection refused")
            r = auth_client.post(
                "/api/settings/test-imap",
                json={
                    "imap_host": "imap.gmail.com",
                    "imap_port": 993,
                    "gmail_address": "test@gmail.com",
                    "gmail_app_password": "secret",
                },
            )
        assert r.status_code == 400

    def test_test_imap_auth_failure(self, auth_client):
        import imaplib

        with patch("imaplib.IMAP4_SSL") as mock_imap:
            mock_instance = MagicMock()
            mock_instance.login.side_effect = imaplib.IMAP4.error("Invalid credentials")
            mock_imap.return_value = mock_instance
            r = auth_client.post(
                "/api/settings/test-imap",
                json={
                    "imap_host": "imap.gmail.com",
                    "imap_port": 993,
                    "gmail_address": "test@gmail.com",
                    "gmail_app_password": "wrong",
                },
            )
        assert r.status_code == 400


class TestAirportSettings:
    def test_get_airport_count(self, auth_client):
        r = auth_client.get("/api/settings/airports/count")
        assert r.status_code == 200
        assert "count" in r.json()
        assert isinstance(r.json()["count"], int)

    def test_reload_airports_admin_only(self, auth_client):
        with patch("backend.database.load_airports_if_empty"):
            r = auth_client.post("/api/settings/airports/reload")
        assert r.status_code == 200
        assert "count" in r.json()

    def test_reload_airports_non_admin_forbidden(self, auth_client, api_app):
        auth_client.post("/api/users", json={"username": "regular", "password": "password123"})
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "regular", "password": "password123"})
            r = c.post("/api/settings/airports/reload")
            assert r.status_code == 403


# ---------------------------------------------------------------------------
# Airport lookup route
# ---------------------------------------------------------------------------


class TestAirportLookup:
    def test_get_airport_not_found(self, auth_client):
        r = auth_client.get("/api/airports/ZZZ")
        assert r.status_code == 404

    def test_get_airport_found(self, auth_client):
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('GRU', 'Guarulhos', 'São Paulo', 'BR', -23.43, -46.47)"
            )
        r = auth_client.get("/api/airports/GRU")
        assert r.status_code == 200
        data = r.json()
        assert data["iata_code"] == "GRU"
        assert data["city_name"] == "São Paulo"

    def test_get_airport_case_insensitive(self, auth_client):
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('ARN', 'Arlanda', 'Stockholm', 'SE', 59.65, 17.93)"
            )
        r = auth_client.get("/api/airports/arn")
        assert r.status_code == 200
        assert r.json()["iata_code"] == "ARN"
