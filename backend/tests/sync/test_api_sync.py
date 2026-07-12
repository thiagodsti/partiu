"""Tests for /api/sync routes."""

from unittest.mock import patch


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
        with patch("backend.sync.pipeline.run_email_sync_for_user"):
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


class TestFullSync:
    def test_full_sync_starts_background(self, auth_client):
        with patch("backend.sync.pipeline.run_email_sync_for_user"):
            r = auth_client.post("/api/sync/full-sync")
        assert r.status_code == 200
        assert r.json()["status"] == "started"

    def test_full_sync_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/sync/full-sync")
        assert r.status_code == 401
