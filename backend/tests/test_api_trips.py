"""Tests for /api/trips routes."""

from unittest.mock import AsyncMock, patch

import pytest


def _make_flight(
    client,
    dep="GRU",
    arr="LHR",
    dep_dt="2025-06-01T10:00:00",
    arr_dt="2025-06-01T22:00:00",
    flight_num="LA8094",
    trip_id=None,
):
    payload = {
        "flight_number": flight_num,
        "departure_airport": dep,
        "departure_datetime": dep_dt,
        "arrival_airport": arr,
        "arrival_datetime": arr_dt,
    }
    if trip_id:
        payload["trip_id"] = trip_id
    with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
        r = client.post("/api/flights", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


# ---------------------------------------------------------------------------
# List & Get
# ---------------------------------------------------------------------------


class TestTripsListGet:
    def test_list_trips_empty(self, auth_client):
        r = auth_client.get("/api/trips")
        assert r.status_code == 200
        assert r.json()["trips"] == []

    def test_list_trips_returns_created(self, auth_client):
        auth_client.post("/api/trips", json={"name": "My Trip"})
        r = auth_client.get("/api/trips")
        trips = r.json()["trips"]
        assert len(trips) == 1
        assert trips[0]["name"] == "My Trip"

    def test_list_trips_has_flight_count(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        _make_flight(auth_client, trip_id=trip_id)
        r2 = auth_client.get("/api/trips")
        trip = r2.json()["trips"][0]
        assert trip["flight_count"] == 1

    def test_list_trips_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/trips")
        assert r.status_code == 401

    def test_get_trip_returns_flights(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        _make_flight(auth_client, trip_id=trip_id)
        r2 = auth_client.get(f"/api/trips/{trip_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["name"] == "My Trip"
        assert len(data["flights"]) == 1

    def test_get_trip_not_found(self, auth_client):
        r = auth_client.get("/api/trips/nonexistent-id")
        assert r.status_code == 404

    def test_get_trip_booking_refs_parsed(self, auth_client):
        auth_client.post("/api/trips", json={"name": "My Trip", "booking_refs": ["ABC123"]})
        r = auth_client.get("/api/trips")
        trip = r.json()["trips"][0]
        assert trip["booking_refs"] == ["ABC123"]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestTripCreate:
    def test_create_trip_minimal(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Beach Holiday"})
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Beach Holiday"
        assert "id" in data

    def test_create_trip_full(self, auth_client):
        r = auth_client.post(
            "/api/trips",
            json={
                "name": "My Trip",
                "booking_refs": ["ABC123", "DEF456"],
                "start_date": "2025-06-01",
                "end_date": "2025-06-15",
                "origin_airport": "GRU",
                "destination_airport": "LHR",
            },
        )
        assert r.status_code == 201

    def test_create_trip_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/trips", json={"name": "My Trip"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestTripUpdate:
    def test_update_trip_name(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Old Name"})
        trip_id = r.json()["id"]
        r2 = auth_client.patch(f"/api/trips/{trip_id}", json={"name": "New Name"})
        assert r2.status_code == 200
        r3 = auth_client.get(f"/api/trips/{trip_id}")
        assert r3.json()["name"] == "New Name"

    def test_update_trip_booking_refs(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        auth_client.patch(f"/api/trips/{trip_id}", json={"booking_refs": ["NEW123"]})
        r2 = auth_client.get(f"/api/trips/{trip_id}")
        assert r2.json()["booking_refs"] == ["NEW123"]

    def test_update_trip_dates(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        auth_client.patch(
            f"/api/trips/{trip_id}",
            json={
                "start_date": "2025-07-01",
                "end_date": "2025-07-10",
                "origin_airport": "GRU",
                "destination_airport": "CDG",
            },
        )
        r2 = auth_client.get(f"/api/trips/{trip_id}")
        assert r2.json()["start_date"] == "2025-07-01"

    def test_update_trip_no_changes(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.patch(f"/api/trips/{trip_id}", json={})
        assert r2.status_code == 200

    def test_update_trip_not_found(self, auth_client):
        r = auth_client.patch("/api/trips/nonexistent", json={"name": "x"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestTripDelete:
    def test_delete_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.delete(f"/api/trips/{trip_id}")
        assert r2.status_code == 204
        r3 = auth_client.get(f"/api/trips/{trip_id}")
        assert r3.status_code == 404

    def test_delete_trip_unlinks_flights(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        fid = _make_flight(auth_client, trip_id=trip_id)
        auth_client.delete(f"/api/trips/{trip_id}")
        # Flight should still exist but with no trip
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.status_code == 200
        assert r2.json()["trip_id"] is None


# ---------------------------------------------------------------------------
# Flight assignment
# ---------------------------------------------------------------------------


class TestFlightAssignment:
    def test_add_flight_to_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        fid = _make_flight(auth_client)
        r2 = auth_client.post(f"/api/trips/{trip_id}/flights/{fid}")
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    def test_add_flight_trip_not_found(self, auth_client):
        fid = _make_flight(auth_client)
        r = auth_client.post(f"/api/trips/bad-trip-id/flights/{fid}")
        assert r.status_code == 404

    def test_add_flight_flight_not_found(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/flights/bad-flight-id")
        assert r2.status_code == 404

    def test_remove_flight_from_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        fid = _make_flight(auth_client, trip_id=trip_id)
        r2 = auth_client.delete(f"/api/trips/{trip_id}/flights/{fid}")
        assert r2.status_code == 200
        r3 = auth_client.get(f"/api/flights/{fid}")
        assert r3.json()["trip_id"] is None


# ---------------------------------------------------------------------------
# Image endpoints
# ---------------------------------------------------------------------------


class TestTripImage:
    def test_get_image_trip_not_found(self, auth_client):
        r = auth_client.get("/api/trips/nonexistent/image")
        assert r.status_code == 404

    def test_get_image_no_city_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        with patch("backend.routes.trips.fetch_trip_image", new=AsyncMock(return_value=False)):
            r2 = auth_client.get(f"/api/trips/{trip_id}/image")
        assert r2.status_code == 404

    def test_get_image_already_failed_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        # Mark image as previously fetched (failed)
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET image_fetched_at = '2025-01-01T00:00:00' WHERE id = ?", (trip_id,)
            )
        r2 = auth_client.get(f"/api/trips/{trip_id}/image")
        assert r2.status_code == 404

    def test_refresh_image_trip_not_found(self, auth_client):
        r = auth_client.post("/api/trips/nonexistent/image/refresh")
        assert r.status_code == 404

    def test_refresh_image_no_city_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "No City"})
        trip_id = r.json()["id"]
        with patch("backend.routes.trips.fetch_trip_image", new=AsyncMock(return_value=False)):
            r2 = auth_client.post(f"/api/trips/{trip_id}/image/refresh")
        assert r2.status_code == 404

    def test_get_image_with_destination_airport_fetches(self, auth_client, tmp_path):
        r = auth_client.post(
            "/api/trips",
            json={
                "name": "London Trip",
                "destination_airport": "LHR",
            },
        )
        trip_id = r.json()["id"]
        # Insert a fake airport
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('LHR', 'Heathrow', 'London', 'GB', 51.47, -0.46)"
            )
        # Mock fetch to succeed and create a fake file
        fake_image = tmp_path / "fake.jpg"
        fake_image.write_bytes(b"\xff\xd8\xff")

        async def _mock_fetch(trip_id, city_name, force_refresh=False):
            import shutil

            from backend.trip_images import trip_image_path

            shutil.copy(str(fake_image), str(trip_image_path(trip_id)))
            return True

        with patch("backend.routes.trips.fetch_trip_image", side_effect=_mock_fetch):
            r2 = auth_client.get(f"/api/trips/{trip_id}/image")
        assert r2.status_code == 200
