"""Tests for trip day notes (planner) endpoints."""

import bcrypt
import pytest
from fastapi.testclient import TestClient


def _make_user(api_app, username: str, password: str = "pass1234") -> TestClient:
    with __import__("backend.database", fromlist=["db_write"]).db_write() as conn:
        ph = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
            (username, ph),
        )
    c = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


class TestListDayNotes:
    def test_empty_list_for_new_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip A"})
        trip_id = r.json()["id"]
        r2 = auth_client.get(f"/api/trips/{trip_id}/day-notes")
        assert r2.status_code == 200
        assert r2.json() == []

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/trips/nonexistent/day-notes")
        assert r.status_code == 401

    def test_unknown_trip_returns_404(self, auth_client):
        r = auth_client.get("/api/trips/does-not-exist/day-notes")
        assert r.status_code == 404

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Private"})
        trip_id = r.json()["id"]
        other = _make_user(api_app, "noter_other1")
        r2 = other.get(f"/api/trips/{trip_id}/day-notes")
        assert r2.status_code == 404


class TestUpsertDayNote:
    def test_create_note(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip B"})
        trip_id = r.json()["id"]
        r2 = auth_client.patch(
            f"/api/trips/{trip_id}/day-notes/2025-06-01",
            json={"content": "## Day 1\n- [ ] Visit museum"},
        )
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    def test_note_appears_in_list(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip C"})
        trip_id = r.json()["id"]
        auth_client.patch(
            f"/api/trips/{trip_id}/day-notes/2025-07-10",
            json={"content": "Arrived!"},
        )
        r2 = auth_client.get(f"/api/trips/{trip_id}/day-notes")
        assert r2.status_code == 200
        notes = r2.json()
        assert len(notes) == 1
        assert notes[0]["date"] == "2025-07-10"
        assert notes[0]["content"] == "Arrived!"

    def test_update_existing_note(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip D"})
        trip_id = r.json()["id"]
        auth_client.patch(
            f"/api/trips/{trip_id}/day-notes/2025-08-01",
            json={"content": "First version"},
        )
        auth_client.patch(
            f"/api/trips/{trip_id}/day-notes/2025-08-01",
            json={"content": "Updated version"},
        )
        r2 = auth_client.get(f"/api/trips/{trip_id}/day-notes")
        notes = r2.json()
        assert len(notes) == 1
        assert notes[0]["content"] == "Updated version"

    def test_invalid_date_format_returns_422(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip E"})
        trip_id = r.json()["id"]
        r2 = auth_client.patch(
            f"/api/trips/{trip_id}/day-notes/not-a-date",
            json={"content": "hello"},
        )
        assert r2.status_code == 422

    def test_other_user_cannot_write_to_unshared_trip(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Private Trip"})
        trip_id = r.json()["id"]
        other = _make_user(api_app, "noter_other2")
        r2 = other.patch(
            f"/api/trips/{trip_id}/day-notes/2025-09-01",
            json={"content": "sneaky"},
        )
        assert r2.status_code == 404

    def test_shared_user_can_write_notes(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Shared Trip"})
        trip_id = r.json()["id"]

        collab = _make_user(api_app, "noter_collab1")
        # Get collab username from the client fixture
        r_me = collab.get("/api/auth/me")
        collab_username = r_me.json()["username"]

        # Owner shares the trip
        r_share = auth_client.post(
            f"/api/trips/{trip_id}/share", json={"username": collab_username}
        )
        assert r_share.status_code == 201

        # Accept the invitation
        invites = collab.get("/api/trips/invitations").json()
        assert len(invites) == 1
        collab.post(f"/api/trips/invitations/{invites[0]['id']}/accept")

        # Collaborator can now write notes
        r2 = collab.patch(
            f"/api/trips/{trip_id}/day-notes/2025-10-01",
            json={"content": "Collab note"},
        )
        assert r2.status_code == 200

        # Owner sees the note
        notes = auth_client.get(f"/api/trips/{trip_id}/day-notes").json()
        assert any(n["content"] == "Collab note" for n in notes)

    def test_multiple_dates(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Multi-day Trip"})
        trip_id = r.json()["id"]
        for d in ["2025-11-01", "2025-11-02", "2025-11-03"]:
            auth_client.patch(
                f"/api/trips/{trip_id}/day-notes/{d}",
                json={"content": f"Note for {d}"},
            )
        notes = auth_client.get(f"/api/trips/{trip_id}/day-notes").json()
        assert len(notes) == 3
        assert [n["date"] for n in notes] == ["2025-11-01", "2025-11-02", "2025-11-03"]

    def test_notes_deleted_with_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Doomed Trip"})
        trip_id = r.json()["id"]
        auth_client.patch(
            f"/api/trips/{trip_id}/day-notes/2025-12-01",
            json={"content": "Should be gone soon"},
        )
        auth_client.delete(f"/api/trips/{trip_id}")
        # Notes cascade-deleted with the trip; trip is gone
        r2 = auth_client.get(f"/api/trips/{trip_id}/day-notes")
        assert r2.status_code == 404
