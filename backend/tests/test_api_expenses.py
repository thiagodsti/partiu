"""Tests for trip expenses endpoints."""

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


class TestListExpenses:
    def test_empty_for_new_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip A"})
        trip_id = r.json()["id"]
        r2 = auth_client.get(f"/api/trips/{trip_id}/expenses")
        assert r2.status_code == 200
        assert r2.json() == []

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/trips/nonexistent/expenses")
        assert r.status_code == 401

    def test_unknown_trip_returns_404(self, auth_client):
        r = auth_client.get("/api/trips/does-not-exist/expenses")
        assert r.status_code == 404

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Private"})
        trip_id = r.json()["id"]
        other = _make_user(api_app, "exp_other1")
        r2 = other.get(f"/api/trips/{trip_id}/expenses")
        assert r2.status_code == 404


class TestCreateExpense:
    def test_create_basic(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip B"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 500.0, "currency": "EUR"},
        )
        assert r2.status_code == 201
        data = r2.json()
        assert data["ok"] is True
        assert "id" in data

    def test_expense_appears_in_list(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip C"})
        trip_id = r.json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Car rental", "amount": 120.5, "currency": "SEK"},
        )
        r2 = auth_client.get(f"/api/trips/{trip_id}/expenses")
        assert r2.status_code == 200
        expenses = r2.json()
        assert len(expenses) == 1
        assert expenses[0]["description"] == "Car rental"
        assert expenses[0]["amount"] == 120.5
        assert expenses[0]["currency"] == "SEK"

    def test_currency_uppercased(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip D"})
        trip_id = r.json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Taxi", "amount": 20.0, "currency": "usd"},
        )
        expenses = auth_client.get(f"/api/trips/{trip_id}/expenses").json()
        assert expenses[0]["currency"] == "USD"

    def test_empty_description_rejected(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip E"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "  ", "amount": 10.0, "currency": "EUR"},
        )
        assert r2.status_code == 400

    def test_zero_amount_rejected(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip F"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Free", "amount": 0.0, "currency": "EUR"},
        )
        assert r2.status_code == 400

    def test_negative_amount_rejected(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip G"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Refund", "amount": -50.0, "currency": "EUR"},
        )
        assert r2.status_code == 400

    def test_unsupported_currency_rejected(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip H"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Item", "amount": 10.0, "currency": "XYZ"},
        )
        assert r2.status_code == 400

    def test_multiple_currencies(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip I"})
        trip_id = r.json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 200.0, "currency": "EUR"},
        )
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Tour", "amount": 1500.0, "currency": "SEK"},
        )
        expenses = auth_client.get(f"/api/trips/{trip_id}/expenses").json()
        assert len(expenses) == 2

    def test_expenses_appear_in_trips_list_total(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip J"})
        trip_id = r.json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 300.0, "currency": "EUR"},
        )
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Food", "amount": 100.0, "currency": "EUR"},
        )
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Train", "amount": 500.0, "currency": "SEK"},
        )
        trips = auth_client.get("/api/trips").json()["trips"]
        trip = next(t for t in trips if t["id"] == trip_id)
        totals = trip["expenses_total"]
        assert totals["EUR"] == pytest.approx(400.0)
        assert totals["SEK"] == pytest.approx(500.0)

    def test_expenses_appear_in_get_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip K"})
        trip_id = r.json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Airbnb", "amount": 800.0, "currency": "USD"},
        )
        trip = auth_client.get(f"/api/trips/{trip_id}").json()
        assert trip["expenses_total"]["USD"] == pytest.approx(800.0)


class TestUpdateExpense:
    def test_update_description(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip L"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Old desc", "amount": 50.0, "currency": "EUR"},
        )
        expense_id = r2.json()["id"]
        r3 = auth_client.patch(
            f"/api/trips/{trip_id}/expenses/{expense_id}",
            json={"description": "New desc"},
        )
        assert r3.status_code == 200
        expenses = auth_client.get(f"/api/trips/{trip_id}/expenses").json()
        assert expenses[0]["description"] == "New desc"

    def test_update_amount(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip M"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 100.0, "currency": "EUR"},
        )
        expense_id = r2.json()["id"]
        auth_client.patch(
            f"/api/trips/{trip_id}/expenses/{expense_id}",
            json={"amount": 250.0},
        )
        expenses = auth_client.get(f"/api/trips/{trip_id}/expenses").json()
        assert expenses[0]["amount"] == pytest.approx(250.0)

    def test_update_nonexistent_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip N"})
        trip_id = r.json()["id"]
        r2 = auth_client.patch(
            f"/api/trips/{trip_id}/expenses/nonexistent-id",
            json={"amount": 100.0},
        )
        assert r2.status_code == 404

    def test_other_user_cannot_update(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Trip O"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 200.0, "currency": "EUR"},
        )
        expense_id = r2.json()["id"]
        other = _make_user(api_app, "exp_other2")
        r3 = other.patch(
            f"/api/trips/{trip_id}/expenses/{expense_id}",
            json={"amount": 999.0},
        )
        assert r3.status_code == 404


class TestDeleteExpense:
    def test_delete_expense(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip P"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 100.0, "currency": "EUR"},
        )
        expense_id = r2.json()["id"]
        r3 = auth_client.delete(f"/api/trips/{trip_id}/expenses/{expense_id}")
        assert r3.status_code == 204
        expenses = auth_client.get(f"/api/trips/{trip_id}/expenses").json()
        assert expenses == []

    def test_delete_nonexistent_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip Q"})
        trip_id = r.json()["id"]
        r2 = auth_client.delete(f"/api/trips/{trip_id}/expenses/does-not-exist")
        assert r2.status_code == 404

    def test_expenses_cascade_delete_with_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Doomed"})
        trip_id = r.json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={"description": "Hotel", "amount": 100.0, "currency": "EUR"},
        )
        auth_client.delete(f"/api/trips/{trip_id}")
        r2 = auth_client.get(f"/api/trips/{trip_id}/expenses")
        assert r2.status_code == 404
