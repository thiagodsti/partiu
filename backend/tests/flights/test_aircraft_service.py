"""Tests for backend.flights.aircraft_service (FlightAircraftService) — cached
result passthrough, hexdb recovery, and the completed-flight OpenSky shortcut."""

import asyncio
import itertools
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _create_body(**overrides) -> dict:
    body = {
        "flight_number": "LA800",
        "airline_name": "LATAM",
        "airline_code": "LA",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00",
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00",
        "booking_reference": "",
        "passenger_name": "",
        "seat": "",
        "cabin_class": "",
        "departure_terminal": "",
        "departure_gate": "",
        "arrival_terminal": "",
        "arrival_gate": "",
        "notes": "",
        "trip_id": None,
    }
    body.update(overrides)
    return body


class TestGetFlightAircraft:
    def test_completed_flight_returns_empty_without_opensky(self, test_db):
        from backend.flights.aircraft_service import FlightAircraftService
        from backend.flights.service import FlightService

        flight_service = FlightService()
        aircraft_service = FlightAircraftService()
        user_id = _seed_user(test_db)
        past = "2020-01-01T10:00:00"
        flight_id = flight_service.create_flight(
            user_id,
            _create_body(departure_datetime=past, arrival_datetime=past),
        )

        with patch(
            "backend.integrations.aircraft.client.get_or_fetch_aircraft", new=AsyncMock()
        ) as mock_fetch:
            result = asyncio.run(aircraft_service.get_flight_aircraft(flight_id, user_id))

        assert result == {}
        mock_fetch.assert_not_called()

    def test_cached_recovers_missing_registration_via_hexdb(self, test_db):
        from backend.flights.aircraft_service import FlightAircraftService
        from backend.flights.repository import FlightRepository
        from backend.flights.service import FlightService

        flight_service = FlightService()
        aircraft_service = FlightAircraftService()
        user_id = _seed_user(test_db)
        flight_id = flight_service.create_flight(user_id, _create_body())
        FlightRepository().update(
            flight_id,
            user_id,
            {
                "aircraft_type": "",
                "aircraft_icao": "abc123",
                "aircraft_registration": "",
                "aircraft_fetched_at": datetime.now(UTC).isoformat(),
            },
        )

        with patch(
            "backend.integrations.aircraft.client._fetch_type_name_from_hexdb",
            new=AsyncMock(return_value=("Boeing 787", "icao_extra", "PR-XYZ")),
        ):
            result = asyncio.run(aircraft_service.get_flight_aircraft(flight_id, user_id))

        assert result["type_name"] == "Boeing 787"
        # Pre-existing quirk (present in the original route too): the response's
        # "registration" is read from the row fetched before recovery ran, so it
        # stays "" here even though the recovered value was persisted to the DB.
        assert result["registration"] == ""
        flight = FlightRepository().get_by_id(flight_id)
        assert flight is not None
        assert flight.aircraft_registration == "PR-XYZ"
