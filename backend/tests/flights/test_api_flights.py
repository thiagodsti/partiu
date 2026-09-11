"""Tests for /api/flights routes."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


def _future_dt(days: int = 30, hour: int = 10) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime(f"%Y-%m-%dT{hour:02d}:00:00")


def _create_flight(client, **kwargs):
    payload = {
        "flight_number": "LA8094",
        "departure_airport": "GRU",
        "departure_datetime": _future_dt(30, 10),
        "arrival_airport": "LHR",
        "arrival_datetime": _future_dt(30, 22),
        **kwargs,
    }
    with patch("backend.integrations.aircraft.sync.fetch_aircraft_for_new_flights"):
        r = client.post("/api/flights", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_airport_coords():
    """Give GRU/LHR coordinates so local→UTC conversion has a zone to use.

    The shared ``test_db`` airports table is empty, which silently degrades
    ``localize_to_utc`` into treating local time as UTC.
    """
    from backend.airports.timezone import _get_airport_timezone
    from backend.database import db_write

    with db_write() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code,"
            " latitude, longitude) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("GRU", "Guarulhos International Airport", "Sao Paulo", "BR", -23.4356, -46.4731),
                ("LHR", "London Heathrow Airport", "London", "GB", 51.4706, -0.4619),
            ],
        )
    _get_airport_timezone.cache_clear()


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
        with patch("backend.integrations.aircraft.sync.fetch_aircraft_for_new_flights"):
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
        with patch("backend.integrations.aircraft.sync.fetch_aircraft_for_new_flights"):
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

    def test_update_full_form_relocalises_times(self, auth_client):
        """The edit-flight form resubmits every field, with the datetimes as
        naive local time at each airport — the same shape create uses."""
        _seed_airport_coords()
        fid = _create_flight(auth_client)
        r = auth_client.patch(
            f"/api/flights/{fid}",
            json={
                "flight_number": "LA8094",
                "airline_code": "LA",
                "airline_name": "LATAM",
                "departure_airport": "GRU",
                "departure_datetime": "2030-06-01T10:00",
                "arrival_airport": "LHR",
                "arrival_datetime": "2030-06-01T22:00",
                "booking_reference": "ABC123",
                "passenger_name": "SILVA/JOAO",
                "seat": "12A",
                "cabin_class": "economy",
                "departure_terminal": "3",
                "departure_gate": "",
                "arrival_terminal": "",
                "arrival_gate": "",
                "notes": "",
            },
        )
        assert r.status_code == 200, r.text
        flight = auth_client.get(f"/api/flights/{fid}").json()
        # GRU is UTC-3, LHR is UTC+1 in June: 13:00Z → 21:00Z, so 8h in the air.
        assert flight["departure_datetime"].startswith("2030-06-01T13:00")
        assert flight["arrival_datetime"].startswith("2030-06-01T21:00")
        assert flight["duration_minutes"] == 480
        assert flight["departure_timezone"] == "America/Sao_Paulo"
        assert flight["arrival_timezone"] == "Europe/London"
        assert flight["seat"] == "12A"
        # A field cleared in the form is cleared on the flight.
        assert flight["arrival_gate"] == ""

    def test_update_times_moves_trip_span(self, auth_client):
        """Editing a flight's times drags its trip's start/end along."""
        trip_id = auth_client.post("/api/trips", json={"name": "Edit span"}).json()["id"]
        fid = _create_flight(auth_client, trip_id=trip_id)

        r = auth_client.patch(
            f"/api/flights/{fid}",
            json={
                "departure_airport": "GRU",
                "departure_datetime": "2030-07-15T10:00",
                "arrival_airport": "LHR",
                "arrival_datetime": "2030-07-15T22:00",
            },
        )
        assert r.status_code == 200, r.text

        trip = auth_client.get(f"/api/trips/{trip_id}").json()
        assert trip["start_date"].startswith("2030-07-15")


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


class TestUngroupFlight:
    def test_ungroup_moves_flight_to_new_trip(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Multi"})
        trip_id = r.json()["id"]
        fid1 = _create_flight(auth_client, trip_id=trip_id)
        fid2 = _create_flight(auth_client, flight_number="LA0002", trip_id=trip_id)

        r = auth_client.post(f"/api/flights/{fid2}/ungroup")
        assert r.status_code == 201
        new_trip_id = r.json()["trip_id"]
        assert new_trip_id != trip_id

        # fid2 is now in the new trip
        r2 = auth_client.get(f"/api/flights/{fid2}")
        assert r2.json()["trip_id"] == new_trip_id

        # fid1 is still in the original trip
        r3 = auth_client.get(f"/api/flights/{fid1}")
        assert r3.json()["trip_id"] == trip_id

    def test_ungroup_new_trip_inherits_airports(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Multi"})
        trip_id = r.json()["id"]
        _create_flight(auth_client, trip_id=trip_id)
        fid2 = _create_flight(
            auth_client,
            flight_number="LA0002",
            departure_airport="LHR",
            arrival_airport="CDG",
            trip_id=trip_id,
        )

        r = auth_client.post(f"/api/flights/{fid2}/ungroup")
        new_trip_id = r.json()["trip_id"]
        r_trip = auth_client.get(f"/api/trips/{new_trip_id}")
        data = r_trip.json()
        assert data["origin_airport"] == "LHR"
        assert data["destination_airport"] == "CDG"

    def test_ungroup_solo_flight_returns_400(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Solo"})
        trip_id = r.json()["id"]
        fid = _create_flight(auth_client, trip_id=trip_id)

        r = auth_client.post(f"/api/flights/{fid}/ungroup")
        assert r.status_code == 400

    def test_ungroup_flight_not_in_trip_returns_400(self, auth_client):
        fid = _create_flight(auth_client)
        r = auth_client.post(f"/api/flights/{fid}/ungroup")
        assert r.status_code == 400

    def test_ungroup_not_found_returns_404(self, auth_client):
        r = auth_client.post("/api/flights/nonexistent/ungroup")
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
        with patch(
            "backend.integrations.aircraft.client.get_or_fetch_aircraft",
            new=AsyncMock(return_value={}),
        ):
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


class TestFlightExport:
    def test_export_csv_empty(self, auth_client):
        r = auth_client.get("/api/flights/export.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        lines = r.text.strip().split("\n")
        # Only header row when no flights
        assert len(lines) == 1
        assert "Flight" in lines[0]

    def test_export_csv_contains_flight(self, auth_client):
        # Export only includes completed (past) flights
        past = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT10:00:00")
        _create_flight(
            auth_client, flight_number="LA8094", departure_datetime=past, arrival_datetime=past
        )
        r = auth_client.get("/api/flights/export.csv")
        assert r.status_code == 200
        lines = r.text.strip().split("\n")
        assert len(lines) == 2  # header + 1 flight
        assert "LA8094" in lines[1]

    def test_export_csv_unauthenticated(self, client):
        r = client.get("/api/flights/export.csv")
        assert r.status_code in (401, 403)
