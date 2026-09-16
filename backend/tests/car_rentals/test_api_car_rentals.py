"""Black-box tests for the car-rental endpoints."""

import bcrypt
from fastapi.testclient import TestClient

from backend.tests.car_rentals.conftest import COUNTER_MUNICH, rental_payload


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


def _trip(client: TestClient, name: str = "Austria 2026") -> str:
    return client.post("/api/trips", json={"name": name}).json()["id"]


class TestList:
    def test_empty_for_a_new_trip(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.get(f"/api/trips/{trip_id}/car-rentals")
        assert r.status_code == 200
        assert r.json() == []

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/api/trips/nope/car-rentals").status_code == 401

    def test_unknown_trip_returns_404(self, auth_client):
        assert auth_client.get("/api/trips/does-not-exist/car-rentals").status_code == 404

    def test_another_users_trip_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        other = _make_user(api_app, "rental_other1")
        assert other.get(f"/api/trips/{trip_id}/car-rentals").status_code == 404


class TestCreate:
    def test_create_returns_201_and_the_computed_fields(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/car-rentals", json=rental_payload())
        assert r.status_code == 201

        rental = auth_client.get(f"/api/trips/{trip_id}/car-rentals").json()[0]
        assert rental["vendor"] == "Hertz"
        assert rental["pickup_date"] == "2026-03-29"
        assert rental["dropoff_date"] == "2026-04-01"
        assert rental["days"] == 3
        assert rental["is_one_way"] is False
        assert rental["vehicle"] == "Fiat 500 or similar"

    def test_a_one_way_rental_reports_itself_as_one(self, auth_client):
        trip_id = _trip(auth_client)
        auth_client.post(
            f"/api/trips/{trip_id}/car-rentals",
            json=rental_payload(pickup=dict(COUNTER_MUNICH)),
        )
        rental = auth_client.get(f"/api/trips/{trip_id}/car-rentals").json()[0]
        assert rental["is_one_way"] is True
        assert rental["pickup"]["name"] == "Munich Airport"
        assert rental["dropoff"]["name"] == "Vienna Airport"

    def test_a_dropoff_before_pickup_returns_400(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/car-rentals",
            json=rental_payload(
                pickup_datetime="2026-04-01T09:00", dropoff_datetime="2026-03-29T09:00"
            ),
        )
        assert r.status_code == 400

    def test_a_missing_vendor_returns_422(self, auth_client):
        trip_id = _trip(auth_client)
        payload = rental_payload()
        del payload["vendor"]
        assert (
            auth_client.post(f"/api/trips/{trip_id}/car-rentals", json=payload).status_code == 422
        )

    def test_creating_on_another_users_trip_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        other = _make_user(api_app, "rental_other2")
        r = other.post(f"/api/trips/{trip_id}/car-rentals", json=rental_payload())
        assert r.status_code == 404


class TestUpdate:
    def test_patch_one_field(self, auth_client):
        trip_id = _trip(auth_client)
        rental_id = auth_client.post(
            f"/api/trips/{trip_id}/car-rentals", json=rental_payload()
        ).json()["id"]

        r = auth_client.patch(
            f"/api/trips/{trip_id}/car-rentals/{rental_id}", json={"vehicle": "VW Golf"}
        )
        assert r.status_code == 200

        rental = auth_client.get(f"/api/trips/{trip_id}/car-rentals").json()[0]
        assert rental["vehicle"] == "VW Golf"
        assert rental["vendor"] == "Hertz"

    def test_unknown_rental_returns_404(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.patch(f"/api/trips/{trip_id}/car-rentals/nope", json={"vehicle": "VW Golf"})
        assert r.status_code == 404


class TestDelete:
    def test_delete_removes_it(self, auth_client):
        trip_id = _trip(auth_client)
        rental_id = auth_client.post(
            f"/api/trips/{trip_id}/car-rentals", json=rental_payload()
        ).json()["id"]

        assert (
            auth_client.delete(f"/api/trips/{trip_id}/car-rentals/{rental_id}").status_code == 200
        )
        assert auth_client.get(f"/api/trips/{trip_id}/car-rentals").json() == []

    def test_unknown_rental_returns_404(self, auth_client):
        trip_id = _trip(auth_client)
        assert auth_client.delete(f"/api/trips/{trip_id}/car-rentals/nope").status_code == 404
