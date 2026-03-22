"""Tests for boarding pass API endpoints."""

import io
from unittest.mock import patch

import pytest


def _make_flight(client, dep="GRU", arr="LHR", dep_dt="2025-06-01T10:00:00", arr_dt="2025-06-01T22:00:00"):
    payload = {
        "flight_number": "LA8094",
        "departure_airport": dep,
        "departure_datetime": dep_dt,
        "arrival_airport": arr,
        "arrival_datetime": arr_dt,
    }
    with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
        r = client.post("/api/flights", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


# Minimal 1×1 PNG
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestListBoardingPasses:
    def test_empty_list(self, auth_client):
        flight_id = _make_flight(auth_client)
        r = auth_client.get(f"/api/flights/{flight_id}/boarding-passes")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_unknown_flight_returns_404(self, auth_client):
        r = auth_client.get("/api/flights/nonexistent/boarding-passes")
        assert r.status_code == 404

    def test_list_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/flights/some-id/boarding-passes")
        assert r.status_code == 401


class TestUploadBoardingPass:
    def test_upload_png(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Point DB to tmp_path so storage dir is created there
        import backend.config as cfg
        monkeypatch.setattr(cfg.settings, "DB_PATH", str(tmp_path / "test.db"))

        flight_id = _make_flight(auth_client)
        r = auth_client.post(
            f"/api/flights/{flight_id}/boarding-passes",
            files={"file": ("boarding.png", io.BytesIO(_PNG_BYTES), "image/png")},
        )
        assert r.status_code == 201
        bp_id = r.json()["id"]
        assert bp_id

        # It should appear in the list
        r2 = auth_client.get(f"/api/flights/{flight_id}/boarding-passes")
        assert len(r2.json()) == 1
        assert r2.json()[0]["id"] == bp_id

    def test_upload_unknown_flight_returns_404(self, auth_client):
        r = auth_client.post(
            "/api/flights/nonexistent/boarding-passes",
            files={"file": ("boarding.png", io.BytesIO(_PNG_BYTES), "image/png")},
        )
        assert r.status_code == 404

    def test_upload_invalid_content_type(self, auth_client):
        flight_id = _make_flight(auth_client)
        r = auth_client.post(
            f"/api/flights/{flight_id}/boarding-passes",
            files={"file": ("boarding.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
        )
        assert r.status_code == 422

    def test_upload_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post(
            "/api/flights/some-id/boarding-passes",
            files={"file": ("boarding.png", io.BytesIO(_PNG_BYTES), "image/png")},
        )
        assert r.status_code == 401


class TestGetBoardingPassImage:
    def test_get_image(self, auth_client, tmp_path, monkeypatch):
        import backend.config as cfg
        monkeypatch.setattr(cfg.settings, "DB_PATH", str(tmp_path / "test.db"))

        flight_id = _make_flight(auth_client)
        r = auth_client.post(
            f"/api/flights/{flight_id}/boarding-passes",
            files={"file": ("boarding.png", io.BytesIO(_PNG_BYTES), "image/png")},
        )
        assert r.status_code == 201
        bp_id = r.json()["id"]

        r2 = auth_client.get(f"/api/boarding-passes/{bp_id}/image")
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("image/png")

    def test_get_image_unknown_returns_404(self, auth_client):
        r = auth_client.get("/api/boarding-passes/nonexistent/image")
        assert r.status_code == 404

    def test_get_image_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/boarding-passes/some-id/image")
        assert r.status_code == 401


class TestDeleteBoardingPass:
    def test_delete(self, auth_client, tmp_path, monkeypatch):
        import backend.config as cfg
        monkeypatch.setattr(cfg.settings, "DB_PATH", str(tmp_path / "test.db"))

        flight_id = _make_flight(auth_client)
        r = auth_client.post(
            f"/api/flights/{flight_id}/boarding-passes",
            files={"file": ("boarding.png", io.BytesIO(_PNG_BYTES), "image/png")},
        )
        bp_id = r.json()["id"]

        r2 = auth_client.delete(f"/api/boarding-passes/{bp_id}")
        assert r2.status_code == 204

        # Should no longer appear in list
        r3 = auth_client.get(f"/api/flights/{flight_id}/boarding-passes")
        assert r3.json() == []

    def test_delete_unknown_returns_404(self, auth_client):
        r = auth_client.delete("/api/boarding-passes/nonexistent")
        assert r.status_code == 404

    def test_delete_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.delete("/api/boarding-passes/some-id")
        assert r.status_code == 401


class TestBoardingPassNotificationPreference:
    def test_preference_defaults_on(self, auth_client):
        r = auth_client.get("/api/notifications/preferences")
        assert r.status_code == 200
        assert r.json().get("boarding_pass") is True

    def test_preference_can_be_disabled(self, auth_client):
        r = auth_client.post(
            "/api/notifications/preferences", json={"boarding_pass": False}
        )
        assert r.status_code == 200
        assert r.json()["boarding_pass"] is False

        r2 = auth_client.get("/api/notifications/preferences")
        assert r2.json()["boarding_pass"] is False

    def test_preference_can_be_re_enabled(self, auth_client):
        auth_client.post("/api/notifications/preferences", json={"boarding_pass": False})
        r = auth_client.post("/api/notifications/preferences", json={"boarding_pass": True})
        assert r.json()["boarding_pass"] is True
