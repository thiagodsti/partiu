"""Tests for /api/flights routes."""

from unittest.mock import AsyncMock, patch

import pytest


def _create_flight(client, **kwargs):
    payload = {
        "flight_number": "LA8094",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00",
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00",
        **kwargs,
    }
    with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
        r = client.post("/api/flights", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestListFlights:
    def test_list_empty(self, auth_client):
        r = auth_client.get("/api/flights")
        assert r.status_code == 200
        data = r.json()
        assert data["flights"] == []
        assert data["total"] == 0

    def test_list_returns_created(self, auth_client):
        _create_flight(auth_client)
        r = auth_client.get("/api/flights")
        assert r.json()["total"] == 1

    def test_list_filter_by_trip_id(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "T"})
        trip_id = r.json()["id"]
        _create_flight(auth_client, trip_id=trip_id)
        _create_flight(auth_client, flight_number="LA0001")

        r2 = auth_client.get(f"/api/flights?trip_id={trip_id}")
        assert r2.json()["total"] == 1

    def test_list_filter_by_status(self, auth_client):
        _create_flight(auth_client)
        r = auth_client.get("/api/flights?status=upcoming")
        assert r.json()["total"] == 1
        r2 = auth_client.get("/api/flights?status=completed")
        assert r2.json()["total"] == 0

    def test_list_pagination(self, auth_client):
        for i in range(5):
            _create_flight(auth_client, flight_number=f"LA{i:04d}")
        r = auth_client.get("/api/flights?limit=2&offset=0")
        assert len(r.json()["flights"]) == 2
        assert r.json()["total"] == 5

    def test_list_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/flights")
        assert r.status_code == 401


class TestGetFlight:
    def test_get_flight(self, auth_client):
        fid = _create_flight(auth_client)
        r = auth_client.get(f"/api/flights/{fid}")
        assert r.status_code == 200
        data = r.json()
        assert data["flight_number"] == "LA8094"
        assert data["departure_airport"] == "GRU"
        assert data["arrival_airport"] == "LHR"

    def test_get_flight_not_found(self, auth_client):
        r = auth_client.get("/api/flights/nonexistent")
        assert r.status_code == 404

    def test_get_flight_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/flights/someid")
        assert r.status_code == 401


class TestCreateFlight:
    def test_create_minimal(self, auth_client):
        with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
            r = auth_client.post(
                "/api/flights",
                json={
                    "flight_number": "SK1234",
                    "departure_airport": "ARN",
                    "departure_datetime": "2025-07-01T08:00:00",
                    "arrival_airport": "FRA",
                    "arrival_datetime": "2025-07-01T10:30:00",
                },
            )
        assert r.status_code == 201
        assert "id" in r.json()

    def test_create_full_fields(self, auth_client):
        with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
            r = auth_client.post(
                "/api/flights",
                json={
                    "flight_number": "LA8094",
                    "airline_name": "LATAM",
                    "airline_code": "LA",
                    "departure_airport": "GRU",
                    "departure_datetime": "2025-06-01T10:00:00",
                    "arrival_airport": "LHR",
                    "arrival_datetime": "2025-06-01T22:00:00",
                    "booking_reference": "ABC123",
                    "passenger_name": "John Doe",
                    "seat": "32A",
                    "cabin_class": "economy",
                    "departure_terminal": "2",
                    "departure_gate": "G10",
                    "arrival_terminal": "3",
                    "arrival_gate": "B5",
                    "notes": "Window seat",
                },
            )
        assert r.status_code == 201

    def test_create_duration_calculated(self, auth_client):
        fid = _create_flight(
            auth_client,
            departure_datetime="2025-06-01T10:00:00",
            arrival_datetime="2025-06-01T14:00:00",
        )
        r = auth_client.get(f"/api/flights/{fid}")
        assert r.json()["duration_minutes"] == 240

    def test_create_with_trip_id(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "T"})
        trip_id = r.json()["id"]
        fid = _create_flight(auth_client, trip_id=trip_id)
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.json()["trip_id"] == trip_id

    def test_create_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post(
            "/api/flights",
            json={
                "flight_number": "LA1",
                "departure_airport": "GRU",
                "departure_datetime": "2025-06-01T10:00:00",
                "arrival_airport": "LHR",
                "arrival_datetime": "2025-06-01T22:00:00",
            },
        )
        assert r.status_code == 401


class TestUpdateFlight:
    def test_update_flight_number(self, auth_client):
        fid = _create_flight(auth_client)
        r = auth_client.patch(f"/api/flights/{fid}", json={"flight_number": "LA9999"})
        assert r.status_code == 200
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.json()["flight_number"] == "LA9999"

    def test_update_flight_no_fields(self, auth_client):
        fid = _create_flight(auth_client)
        r = auth_client.patch(f"/api/flights/{fid}", json={})
        assert r.status_code == 200

    def test_update_flight_not_found(self, auth_client):
        r = auth_client.patch("/api/flights/nonexistent", json={"flight_number": "X"})
        assert r.status_code == 404

    def test_update_flight_status(self, auth_client):
        fid = _create_flight(auth_client)
        auth_client.patch(f"/api/flights/{fid}", json={"status": "completed"})
        r = auth_client.get(f"/api/flights/{fid}")
        assert r.json()["status"] == "completed"

    def test_update_multiple_fields(self, auth_client):
        fid = _create_flight(auth_client)
        auth_client.patch(
            f"/api/flights/{fid}",
            json={
                "seat": "12B",
                "cabin_class": "business",
                "notes": "Upgraded",
            },
        )
        r = auth_client.get(f"/api/flights/{fid}")
        assert r.json()["seat"] == "12B"
        assert r.json()["cabin_class"] == "business"


class TestDeleteFlight:
    def test_delete_flight(self, auth_client):
        fid = _create_flight(auth_client)
        r = auth_client.delete(f"/api/flights/{fid}")
        assert r.status_code == 204
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.status_code == 404

    def test_delete_nonexistent_returns_404(self, auth_client):
        r = auth_client.delete("/api/flights/nonexistent")
        assert r.status_code == 404


class TestFlightEmail:
    def test_get_email_data(self, auth_client):
        fid = _create_flight(auth_client)
        r = auth_client.get(f"/api/flights/{fid}/email")
        assert r.status_code == 200
        data = r.json()
        assert "html_body" in data
        assert "email_subject" in data
        assert "email_date" in data

    def test_get_email_not_found(self, auth_client):
        r = auth_client.get("/api/flights/nonexistent/email")
        assert r.status_code == 404


class TestFlightAircraft:
    def test_get_aircraft_no_cache_future_flight(self, auth_client):
        # Flight with no aircraft cache — triggers OpenSky lookup (mocked)
        fid = _create_flight(auth_client)
        with patch("backend.aircraft_api.get_or_fetch_aircraft", new=AsyncMock(return_value={})):
            r = auth_client.get(f"/api/flights/{fid}/aircraft")
        assert r.status_code == 200
        assert r.json() == {}

    def test_get_aircraft_not_found(self, auth_client):
        r = auth_client.get("/api/flights/nonexistent/aircraft")
        assert r.status_code == 404

    def test_get_aircraft_cached(self, auth_client):
        fid = _create_flight(auth_client)
        from datetime import UTC, datetime

        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET aircraft_type='Boeing 787', aircraft_icao='abc123', "
                "aircraft_registration='PR-XYZ', aircraft_fetched_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), fid),
            )
        r = auth_client.get(f"/api/flights/{fid}/aircraft")
        assert r.status_code == 200
        data = r.json()
        assert data["type_name"] == "Boeing 787"
        assert data["icao24"] == "abc123"
