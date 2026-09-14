"""Tests for /api/settings and related admin routes."""

from unittest.mock import MagicMock, patch

import pytest

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
        with patch("backend.airports.repository.AirportRepository.load_from_csv_if_empty"):
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
# Non-flight domains routes
# ---------------------------------------------------------------------------


class TestNonFlightDomains:
    def test_list_returns_list(self, auth_client):
        r = auth_client.get("/api/settings/admin/non-flight-domains")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        # Each entry has the expected shape
        if r.json():
            entry = r.json()[0]
            assert "domain" in entry
            assert "note" in entry
            assert "created_at" in entry

    def test_add_and_list(self, auth_client):
        r = auth_client.post(
            "/api/settings/admin/non-flight-domains",
            json={"domain": "bookatable.com"},
        )
        assert r.status_code == 200
        assert r.json()["domain"] == "bookatable.com"

        r2 = auth_client.get("/api/settings/admin/non-flight-domains")
        domains = [d["domain"] for d in r2.json()]
        assert "bookatable.com" in domains

    def test_add_duplicate_is_idempotent(self, auth_client):
        auth_client.post("/api/settings/admin/non-flight-domains", json={"domain": "example.com"})
        r = auth_client.post(
            "/api/settings/admin/non-flight-domains", json={"domain": "example.com"}
        )
        assert r.status_code == 200
        r2 = auth_client.get("/api/settings/admin/non-flight-domains")
        assert sum(1 for d in r2.json() if d["domain"] == "example.com") == 1

    def test_delete(self, auth_client):
        auth_client.post("/api/settings/admin/non-flight-domains", json={"domain": "remove-me.com"})
        r = auth_client.delete("/api/settings/admin/non-flight-domains/remove-me.com")
        assert r.status_code == 200
        r2 = auth_client.get("/api/settings/admin/non-flight-domains")
        assert all(d["domain"] != "remove-me.com" for d in r2.json())

    def test_non_admin_forbidden(self, auth_client, api_app):
        auth_client.post("/api/users", json={"username": "regular", "password": "password123"})
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "regular", "password": "password123"})
            assert c.get("/api/settings/admin/non-flight-domains").status_code == 403
            assert (
                c.post(
                    "/api/settings/admin/non-flight-domains", json={"domain": "x.com"}
                ).status_code
                == 403
            )

    def test_unauthenticated_forbidden(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        assert client.get("/api/settings/admin/non-flight-domains").status_code == 401


class TestAirportRankingVisibility:
    """The ranking columns are what let name resolution prefer a large scheduled
    airport over a small one sharing its city's name. Without them, "London" in
    a Ryanair itinerary resolved to London **Ontario**, and a Swedish traveller's
    statistics claimed Canada and the United States.

    It was a startup log line and nothing else, which is why it went unnoticed
    for months; the count is reported so Settings can say so.
    """

    def test_reports_how_many_airports_are_ranked(self, auth_client):
        from backend.database import db_write

        with db_write() as conn:
            conn.execute("DELETE FROM airports")
            conn.execute(
                """INSERT INTO airports (iata_code, name, city_name, country_code, type)
                   VALUES ('LHR', 'Heathrow', 'London', 'GB', 'large_airport')"""
            )
            conn.execute(
                """INSERT INTO airports (iata_code, name, city_name, country_code, type)
                   VALUES ('YXU', 'London Intl', 'London', 'CA', NULL)"""
            )

        data = auth_client.get("/api/settings/airports/count").json()

        assert data["count"] == 2
        assert data["ranked"] == 1

    def test_a_fully_ranked_table_reports_no_gap(self, auth_client):
        from backend.database import db_write

        with db_write() as conn:
            conn.execute("DELETE FROM airports")
            conn.execute(
                """INSERT INTO airports (iata_code, name, city_name, country_code, type)
                   VALUES ('LHR', 'Heathrow', 'London', 'GB', 'large_airport')"""
            )

        data = auth_client.get("/api/settings/airports/count").json()

        assert data["count"] == data["ranked"] == 1
