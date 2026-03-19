"""Tests for backend.aircraft_api."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLookupTypeName:
    def test_empty_string_returns_none(self, test_db):
        from backend.aircraft_api import _lookup_type_name

        assert _lookup_type_name("") is None

    def test_none_returns_none(self, test_db):
        from backend.aircraft_api import _lookup_type_name

        assert _lookup_type_name(None) is None

    def test_existing_type_found(self, test_db):
        from backend.aircraft_api import _lookup_type_name
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO aircraft_types (iata_code, name) VALUES (?, ?)",
                ("B77W", "Boeing 777-300ER"),
            )
        assert _lookup_type_name("B77W") == "Boeing 777-300ER"

    def test_case_insensitive_lookup(self, test_db):
        from backend.aircraft_api import _lookup_type_name
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO aircraft_types (iata_code, name) VALUES (?, ?)",
                ("A320", "Airbus A320"),
            )
        assert _lookup_type_name("a320") == "Airbus A320"

    def test_missing_type_returns_none(self, test_db):
        from backend.aircraft_api import _lookup_type_name

        assert _lookup_type_name("XXXX") is None


class TestFetchTypeNameFromHexdb:
    def test_empty_icao24_returns_empty(self):
        from backend.aircraft_api import _fetch_type_name_from_hexdb

        result = asyncio.run(_fetch_type_name_from_hexdb(""))
        assert result[0] == ""

    def test_http_error_returns_empty(self):
        from backend.aircraft_api import _fetch_type_name_from_hexdb

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_type_name_from_hexdb("abc123"))
        assert result[0] == ""

    def test_exception_returns_empty(self):
        from backend.aircraft_api import _fetch_type_name_from_hexdb

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_type_name_from_hexdb("abc123"))
        assert result[0] == ""

    def test_successful_lookup_builds_name(self, test_db):
        from backend.aircraft_api import _fetch_type_name_from_hexdb

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(
            return_value={
                "ICAOTypeCode": "B789",
                "Manufacturer": "Boeing",
                "Type": "787-9 Dreamliner",
                "Registration": "N12345",
            }
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            name, iata, reg = asyncio.run(_fetch_type_name_from_hexdb("abc123"))
        assert "Boeing" in name or iata == "B789"
        assert reg == "N12345"

    def test_no_manufacturer_returns_empty_name(self, test_db):
        from backend.aircraft_api import _fetch_type_name_from_hexdb

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(
            return_value={
                "ICAOTypeCode": "",
                "Manufacturer": "",
                "Type": "",
                "Registration": "PP-XYZ",
            }
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            name, iata, reg = asyncio.run(_fetch_type_name_from_hexdb("abc123"))
        assert name == ""
        assert reg == "PP-XYZ"


class TestResolveAircraftName:
    def test_local_table_hit_returns_name(self, test_db):
        from backend.aircraft_api import resolve_aircraft_name
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO aircraft_types (iata_code, name) VALUES (?, ?)",
                ("ZTST", "ZTest Aircraft"),
            )
        result = asyncio.run(resolve_aircraft_name("ZTST", ""))
        assert result == "ZTest Aircraft"

    def test_fallback_to_raw_iata_code(self, test_db):
        from backend.aircraft_api import resolve_aircraft_name

        with patch(
            "backend.aircraft_api._fetch_type_name_from_hexdb",
            new=AsyncMock(return_value=("", "", "")),
        ):
            result = asyncio.run(resolve_aircraft_name("ZZZQ", ""))
        assert result == "ZZZQ"

    def test_hexdb_fallback_used_when_no_local(self, test_db):
        from backend.aircraft_api import resolve_aircraft_name

        with patch(
            "backend.aircraft_api._fetch_type_name_from_hexdb",
            new=AsyncMock(return_value=("Boeing 737-800", "B738", "")),
        ):
            result = asyncio.run(resolve_aircraft_name("ZZXX", "abc123"))
        assert result == "Boeing 737-800"

    def test_empty_everything_returns_empty(self, test_db):
        from backend.aircraft_api import resolve_aircraft_name

        with patch(
            "backend.aircraft_api._fetch_type_name_from_hexdb",
            new=AsyncMock(return_value=("", "", "")),
        ):
            result = asyncio.run(resolve_aircraft_name("", ""))
        assert result == ""


class TestFetchViaAviationStack:
    def test_success(self):
        from backend.aircraft_api import _fetch_via_aviationstack

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(
            return_value={
                "data": [
                    {
                        "aircraft": {
                            "icao24": "abc123",
                            "iata": "B77W",
                            "registration": "N123XX",
                        }
                    }
                ]
            }
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_aviationstack("LA123", "test_key"))
        assert result["icao24"] == "ABC123"
        assert result["iata_code"] == "B77W"
        assert result["registration"] == "N123XX"

    def test_http_error_returns_empty(self):
        from backend.aircraft_api import _fetch_via_aviationstack

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_aviationstack("LA123", "test_key"))
        assert result == {}

    def test_timeout_returns_empty(self):
        import httpx

        from backend.aircraft_api import _fetch_via_aviationstack

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_aviationstack("LA123", "test_key"))
        assert result == {}

    def test_empty_data_returns_empty(self):
        from backend.aircraft_api import _fetch_via_aviationstack

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"data": []})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_aviationstack("LA123", "test_key"))
        assert result == {}

    def test_general_exception_returns_empty(self):
        from backend.aircraft_api import _fetch_via_aviationstack

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("unexpected"))
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_aviationstack("LA123", "test_key"))
        assert result == {}


class TestFetchViaOpensky:
    def test_success(self):
        from backend.aircraft_api import _fetch_via_opensky

        states_resp = MagicMock()
        states_resp.status_code = 200
        states_resp.json = MagicMock(return_value={"states": [["abc123", "LA123  "]]})
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json = MagicMock(return_value={"typecode": "B738"})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[states_resp, meta_resp])
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_opensky("LA123"))
        assert result["icao24"] == "ABC123"
        assert result["iata_code"] == "B738"

    def test_empty_states_returns_empty(self):
        from backend.aircraft_api import _fetch_via_opensky

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"states": []})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_opensky("LA123"))
        assert result == {}

    def test_http_error_returns_empty(self):
        from backend.aircraft_api import _fetch_via_opensky

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_opensky("LA123"))
        assert result == {}

    def test_timeout_returns_empty(self):
        import httpx

        from backend.aircraft_api import _fetch_via_opensky

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_opensky("LA123"))
        assert result == {}

    def test_empty_icao24_in_state_returns_empty(self):
        from backend.aircraft_api import _fetch_via_opensky

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"states": [["", "LA123  "]]})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = asyncio.run(_fetch_via_opensky("LA123"))
        assert result == {}


class TestFetchAircraftInfo:
    def test_uses_aviationstack_when_key_configured(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.aircraft_api import fetch_aircraft_info

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "test_key")
        raw = {"icao24": "ABC123", "iata_code": "B738", "registration": "N123"}
        with patch(
            "backend.aircraft_api._fetch_via_aviationstack", new=AsyncMock(return_value=raw)
        ):
            with patch(
                "backend.aircraft_api.resolve_aircraft_name",
                new=AsyncMock(return_value="Boeing 737-800"),
            ):
                result = asyncio.run(fetch_aircraft_info("LA123"))
        assert result["icao24"] == "ABC123"
        assert result["type_name"] == "Boeing 737-800"

    def test_falls_back_to_opensky_when_no_key(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.aircraft_api import fetch_aircraft_info

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "")
        raw = {"icao24": "DEF456", "iata_code": "A320", "registration": ""}
        with patch("backend.aircraft_api._fetch_via_opensky", new=AsyncMock(return_value=raw)):
            with patch(
                "backend.aircraft_api.resolve_aircraft_name",
                new=AsyncMock(return_value="Airbus A320"),
            ):
                result = asyncio.run(fetch_aircraft_info("LA456"))
        assert result["icao24"] == "DEF456"
        assert result["type_name"] == "Airbus A320"

    def test_no_data_returns_empty_dict(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.aircraft_api import fetch_aircraft_info

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "")
        with patch("backend.aircraft_api._fetch_via_opensky", new=AsyncMock(return_value={})):
            result = asyncio.run(fetch_aircraft_info("LA999"))
        assert result == {}

    def test_aviationstack_empty_falls_back_to_opensky(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.aircraft_api import fetch_aircraft_info

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "key")
        raw = {"icao24": "OPEN01", "iata_code": "E190", "registration": ""}
        with patch("backend.aircraft_api._fetch_via_aviationstack", new=AsyncMock(return_value={})):
            with patch("backend.aircraft_api._fetch_via_opensky", new=AsyncMock(return_value=raw)):
                with patch(
                    "backend.aircraft_api.resolve_aircraft_name",
                    new=AsyncMock(return_value="Embraer 190"),
                ):
                    result = asyncio.run(fetch_aircraft_info("AD100"))
        assert result["icao24"] == "OPEN01"


class TestGetOrFetchAircraft:
    def _insert_flight(
        self, conn, flight_id, aircraft_type=None, aircraft_icao=None, aircraft_fetched_at=None
    ):
        conn.execute(
            """INSERT INTO flights (id, flight_number, departure_airport, arrival_airport,
               departure_datetime, arrival_datetime, aircraft_type, aircraft_icao,
               aircraft_fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                flight_id,
                "LA100",
                "GRU",
                "SCL",
                "2024-01-01T10:00:00",
                "2024-01-01T14:00:00",
                aircraft_type,
                aircraft_icao,
                aircraft_fetched_at,
            ),
        )

    def _flight_insert(
        self,
        conn,
        flight_id,
        flight_number,
        aircraft_type=None,
        aircraft_icao=None,
        aircraft_fetched_at=None,
    ):
        now = "2024-01-01T00:00:00"
        conn.execute(
            """INSERT INTO flights (id, flight_number, departure_airport, arrival_airport,
               departure_datetime, arrival_datetime, aircraft_type, aircraft_icao,
               aircraft_fetched_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                flight_id,
                flight_number,
                "GRU",
                "SCL",
                "2024-01-01T10:00:00",
                "2024-01-01T14:00:00",
                aircraft_type,
                aircraft_icao,
                aircraft_fetched_at,
                now,
                now,
            ),
        )

    def test_returns_cached_data(self, test_db):
        from backend.aircraft_api import get_or_fetch_aircraft
        from backend.database import db_write

        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            conn.execute(
                """INSERT INTO flights (id, flight_number, departure_airport, arrival_airport,
                   departure_datetime, arrival_datetime, aircraft_type, aircraft_icao,
                   aircraft_registration, aircraft_fetched_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    flight_id,
                    "LA100",
                    "GRU",
                    "SCL",
                    "2024-01-01T10:00:00",
                    "2024-01-01T14:00:00",
                    "Boeing 777",
                    "ABC123",
                    "CC-BGO",
                    "2024-01-01T15:00:00",
                    "2024-01-01T00:00:00",
                    "2024-01-01T00:00:00",
                ),
            )
        result = asyncio.run(get_or_fetch_aircraft(flight_id, "LA100"))
        assert result["type_name"] == "Boeing 777"
        assert result["icao24"] == "ABC123"
        assert result["fetched_at"] == "2024-01-01T15:00:00"

    def test_fetches_and_stores_when_not_cached(self, test_db):
        from backend.aircraft_api import get_or_fetch_aircraft
        from backend.database import db_write

        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            self._flight_insert(conn, flight_id, "LA200")
        info = {
            "icao24": "XYZ789",
            "iata_code": "B738",
            "type_name": "Boeing 737-800",
            "registration": "PP-XYZ",
        }
        with patch("backend.aircraft_api.fetch_aircraft_info", new=AsyncMock(return_value=info)):
            result = asyncio.run(get_or_fetch_aircraft(flight_id, "LA200"))
        assert result["icao24"] == "XYZ789"
        assert result["type_name"] == "Boeing 737-800"
        assert result["registration"] == "PP-XYZ"

    def test_empty_info_stores_empty_values(self, test_db):
        from backend.aircraft_api import get_or_fetch_aircraft
        from backend.database import db_write

        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            self._flight_insert(conn, flight_id, "LA300")
        with patch("backend.aircraft_api.fetch_aircraft_info", new=AsyncMock(return_value={})):
            result = asyncio.run(get_or_fetch_aircraft(flight_id, "LA300"))
        assert result["type_name"] == ""
        assert result["icao24"] == ""
