"""Tests for backend.aircraft_sync."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _insert_flight(
    conn, flight_id, flight_number, dep_dt, arr_dt, aircraft_fetched_at=None, status="upcoming"
):
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO flights (id, flight_number, departure_airport, arrival_airport,
           departure_datetime, arrival_datetime, aircraft_fetched_at, status,
           created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            flight_id,
            flight_number,
            "GRU",
            "SCL",
            dep_dt,
            arr_dt,
            aircraft_fetched_at,
            status,
            now,
            now,
        ),
    )


class TestRunAircraftSync:
    def test_returns_dict_with_expected_keys(self, test_db):
        from backend.aircraft_sync import run_aircraft_sync

        result = run_aircraft_sync()
        assert "attempted" in result
        assert "updated" in result
        assert "given_up" in result

    def test_no_flights_returns_zeros(self, test_db):
        from backend.aircraft_sync import run_aircraft_sync

        result = run_aircraft_sync()
        assert result["attempted"] == 0
        assert result["updated"] == 0
        assert result["given_up"] == 0

    def test_cancelled_flights_are_skipped(self, test_db):
        from backend.aircraft_sync import run_aircraft_sync
        from backend.database import db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA100",
                (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=2)).isoformat(),
                status="cancelled",
            )
        with patch(
            "backend.aircraft_sync._fetch_rows",
            new=AsyncMock(return_value={"attempted": 0, "updated": 0, "given_up": 0}),
        ):
            result = run_aircraft_sync()
        assert result["attempted"] == 0


class TestFetchAircraftForNewFlights:
    def test_empty_list_is_noop(self, test_db):
        from backend.aircraft_sync import fetch_aircraft_for_new_flights

        fetch_aircraft_for_new_flights([])  # Should not raise

    def test_non_empty_list_attempts_fetch(self, test_db):
        from backend.aircraft_sync import fetch_aircraft_for_new_flights
        from backend.database import db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA300",
                (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=3)).isoformat(),
            )
        with patch(
            "backend.aircraft_sync._fetch_rows",
            new=AsyncMock(return_value={"attempted": 1, "updated": 0, "given_up": 0}),
        ):
            fetch_aircraft_for_new_flights([flight_id])  # should not raise

    def test_already_fetched_flight_is_skipped(self, test_db):
        from backend.aircraft_sync import fetch_aircraft_for_new_flights
        from backend.database import db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA400",
                (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=3)).isoformat(),
                aircraft_fetched_at=now.isoformat(),
            )
        with patch(
            "backend.aircraft_sync._fetch_rows",
            new=AsyncMock(return_value={"attempted": 0, "updated": 0, "given_up": 0}),
        ) as mock_fetch:
            fetch_aircraft_for_new_flights([flight_id])
            # _fetch_rows should not be called since flight is already fetched
            mock_fetch.assert_not_called()


class TestFetchRows:
    def test_gives_up_on_old_arrivals(self, test_db):
        from backend.aircraft_sync import _fetch_rows
        from backend.database import db_conn, db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        old_arr = (now - timedelta(hours=30)).isoformat()
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA400",
                (now - timedelta(hours=35)).isoformat(),
                old_arr,
            )
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, flight_number, arrival_datetime FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchall()
        with patch("backend.aircraft_api.fetch_aircraft_info", new=AsyncMock(return_value={})):
            result = asyncio.run(_fetch_rows(rows))
        assert result["given_up"] == 1
        assert result["attempted"] == 0

    def test_updates_flight_when_info_found(self, test_db):
        from backend.aircraft_sync import _fetch_rows
        from backend.database import db_conn, db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        arr = (now + timedelta(hours=3)).isoformat()
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA500",
                (now - timedelta(hours=1)).isoformat(),
                arr,
            )
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, flight_number, arrival_datetime FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchall()
        info = {
            "icao24": "ICAO01",
            "iata_code": "B738",
            "type_name": "Boeing 737-800",
            "registration": "PP-X",
        }
        with patch("backend.aircraft_api.fetch_aircraft_info", new=AsyncMock(return_value=info)):
            result = asyncio.run(_fetch_rows(rows))
        assert result["updated"] == 1
        assert result["attempted"] == 1
        assert result["given_up"] == 0

    def test_schedules_retry_when_no_info(self, test_db):
        from backend.aircraft_sync import _fetch_rows
        from backend.database import db_conn, db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        arr = (now + timedelta(hours=3)).isoformat()
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA600",
                (now - timedelta(hours=1)).isoformat(),
                arr,
            )
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, flight_number, arrival_datetime FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchall()
        with patch("backend.aircraft_api.fetch_aircraft_info", new=AsyncMock(return_value={})):
            result = asyncio.run(_fetch_rows(rows))
        assert result["attempted"] == 1
        assert result["updated"] == 0
        assert result["given_up"] == 0
        # Verify retry was scheduled
        with db_conn() as conn:
            row = conn.execute(
                "SELECT aircraft_fetch_attempts, aircraft_next_retry_at FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchone()
        assert row["aircraft_fetch_attempts"] == 1
        assert row["aircraft_next_retry_at"] is not None

    def test_invalid_arrival_datetime_still_attempts(self, test_db):
        from backend.aircraft_sync import _fetch_rows
        from backend.database import db_conn, db_write

        flight_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with db_write() as conn:
            _insert_flight(
                conn,
                flight_id,
                "LA700",
                (now - timedelta(hours=1)).isoformat(),
                "not-a-valid-datetime",
            )
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT id, flight_number, arrival_datetime FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchall()
        info = {
            "icao24": "TEST01",
            "iata_code": "B738",
            "type_name": "Boeing 737",
            "registration": "",
        }
        with patch("backend.aircraft_api.fetch_aircraft_info", new=AsyncMock(return_value=info)):
            result = asyncio.run(_fetch_rows(rows))
        assert result["attempted"] == 1


class TestRecoverMissingAircraftNames:
    def test_no_eligible_flights_returns_zero(self, test_db):
        from backend.aircraft_sync import _recover_missing_aircraft_names

        result = asyncio.run(_recover_missing_aircraft_names())
        assert result == 0

    def test_recovers_flight_with_icao_but_no_type(self, test_db):
        from backend.aircraft_sync import _recover_missing_aircraft_names
        from backend.database import db_conn, db_write

        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            conn.execute(
                """INSERT INTO flights (id, flight_number, departure_airport, arrival_airport,
                   departure_datetime, arrival_datetime, aircraft_icao, aircraft_type,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    flight_id,
                    "LA800",
                    "GRU",
                    "SCL",
                    "2024-01-01T10:00:00",
                    "2024-01-01T14:00:00",
                    "ABC123",
                    "",
                    "2024-01-01T00:00:00",
                    "2024-01-01T00:00:00",
                ),
            )
        with patch(
            "backend.aircraft_api._fetch_type_name_from_hexdb",
            new=AsyncMock(return_value=("Boeing 737-800", "B738", "PP-XYZ")),
        ):
            result = asyncio.run(_recover_missing_aircraft_names())
        assert result == 1
        with db_conn() as conn:
            row = conn.execute(
                "SELECT aircraft_type, aircraft_registration FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchone()
        assert row["aircraft_type"] == "Boeing 737-800"
        assert row["aircraft_registration"] == "PP-XYZ"
