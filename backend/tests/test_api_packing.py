"""Tests for packing list endpoints."""

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


class TestListPackingItems:
    def test_empty_for_new_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip A"})
        trip_id = r.json()["id"]
        r2 = auth_client.get(f"/api/trips/{trip_id}/packing")
        assert r2.status_code == 200
        assert r2.json() == []

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/trips/nonexistent/packing")
        assert r.status_code == 401

    def test_unknown_trip_returns_404(self, auth_client):
        r = auth_client.get("/api/trips/does-not-exist/packing")
        assert r.status_code == 404

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Private"})
        trip_id = r.json()["id"]
        other = _make_user(api_app, "pack_other1")
        r2 = other.get(f"/api/trips/{trip_id}/packing")
        assert r2.status_code == 404


class TestCreatePackingItem:
    def test_create_basic(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip B"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Toothbrush"})
        assert r2.status_code == 201
        data = r2.json()
        assert data["ok"] is True
        assert "id" in data

    def test_item_appears_in_list(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip C"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Passport"})
        r2 = auth_client.get(f"/api/trips/{trip_id}/packing")
        assert r2.status_code == 200
        items = r2.json()
        assert len(items) == 1
        assert items[0]["text"] == "Passport"
        assert items[0]["checked"] == 0

    def test_empty_text_rejected(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip D"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "  "})
        assert r2.status_code == 400

    def test_sort_order_increments(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip E"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Item 1"})
        auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Item 2"})
        auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Item 3"})
        items = auth_client.get(f"/api/trips/{trip_id}/packing").json()
        orders = [i["sort_order"] for i in items]
        assert orders == sorted(orders)


class TestUpdatePackingItem:
    def test_toggle_checked(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip F"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Sunscreen"})
        item_id = r2.json()["id"]

        r3 = auth_client.patch(f"/api/trips/{trip_id}/packing/{item_id}", json={"checked": True})
        assert r3.status_code == 200
        item = auth_client.get(f"/api/trips/{trip_id}/packing").json()[0]
        assert item["checked"] == 1

        auth_client.patch(f"/api/trips/{trip_id}/packing/{item_id}", json={"checked": False})
        item = auth_client.get(f"/api/trips/{trip_id}/packing").json()[0]
        assert item["checked"] == 0

    def test_edit_text(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip G"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Old name"})
        item_id = r2.json()["id"]

        r3 = auth_client.patch(f"/api/trips/{trip_id}/packing/{item_id}", json={"text": "New name"})
        assert r3.status_code == 200
        item = auth_client.get(f"/api/trips/{trip_id}/packing").json()[0]
        assert item["text"] == "New name"

    def test_empty_text_rejected(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip H"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Shoes"})
        item_id = r2.json()["id"]
        r3 = auth_client.patch(f"/api/trips/{trip_id}/packing/{item_id}", json={"text": "  "})
        assert r3.status_code == 400

    def test_unknown_item_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip I"})
        trip_id = r.json()["id"]
        r2 = auth_client.patch(
            f"/api/trips/{trip_id}/packing/nonexistent-id", json={"checked": True}
        )
        assert r2.status_code == 404


class TestDeletePackingItem:
    def test_delete_item(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip J"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Camera"})
        item_id = r2.json()["id"]

        r3 = auth_client.delete(f"/api/trips/{trip_id}/packing/{item_id}")
        assert r3.status_code == 204
        assert auth_client.get(f"/api/trips/{trip_id}/packing").json() == []

    def test_delete_unknown_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip K"})
        trip_id = r.json()["id"]
        r2 = auth_client.delete(f"/api/trips/{trip_id}/packing/nonexistent-id")
        assert r2.status_code == 404


class TestClearChecked:
    def test_clear_removes_only_checked(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip L"})
        trip_id = r.json()["id"]

        auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Unchecked"})
        r2 = auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Checked"})
        item2_id = r2.json()["id"]
        auth_client.patch(f"/api/trips/{trip_id}/packing/{item2_id}", json={"checked": True})

        r3 = auth_client.post(f"/api/trips/{trip_id}/packing/clear-checked")
        assert r3.status_code == 204

        remaining = auth_client.get(f"/api/trips/{trip_id}/packing").json()
        assert len(remaining) == 1
        assert remaining[0]["text"] == "Unchecked"

    def test_clear_no_checked_is_noop(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip M"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/packing", json={"text": "Item"})

        r2 = auth_client.post(f"/api/trips/{trip_id}/packing/clear-checked")
        assert r2.status_code == 204
        assert len(auth_client.get(f"/api/trips/{trip_id}/packing").json()) == 1
