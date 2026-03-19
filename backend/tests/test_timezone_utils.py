"""Tests for backend.timezone_utils."""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

import pytest


class TestLocalizeToUtc:
    def test_naive_datetime_falls_back_to_utc(self, test_db):
        from backend.timezone_utils import localize_to_utc

        # Unknown airport — should fall back to treating as UTC
        dt = datetime(2025, 6, 1, 10, 0, 0)
        result = localize_to_utc(dt, "ZZZ")
        assert result.tzinfo is not None

    def test_aware_datetime_converted_to_utc(self, test_db):
        from backend.timezone_utils import localize_to_utc

        # +03:00 aware datetime
        tz_plus3 = timezone(timedelta(hours=3))
        dt = datetime(2025, 6, 1, 13, 0, 0, tzinfo=tz_plus3)
        result = localize_to_utc(dt, "GRU")
        assert result.tzinfo == UTC
        assert result.hour == 10  # 13:00 +03:00 = 10:00 UTC

    def test_none_input_returns_none(self, test_db):
        from backend.timezone_utils import localize_to_utc

        result = localize_to_utc(None, "GRU")
        assert result is None

    def test_known_airport_timezone(self, test_db):
        from backend.database import db_write
        from backend.timezone_utils import _get_airport_timezone, localize_to_utc

        # Clear LRU cache for the airport
        _get_airport_timezone.cache_clear()

        # Insert GRU with real coordinates
        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('GRU', 'Guarulhos', 'São Paulo', 'BR', -23.43, -46.47)"
            )

        _get_airport_timezone.cache_clear()
        # Naive local time at GRU (America/Sao_Paulo, UTC-3)
        dt = datetime(2025, 6, 1, 10, 0, 0)  # local time
        result = localize_to_utc(dt, "GRU")
        assert result.tzinfo is not None
        # GRU is UTC-3, so 10:00 local = 13:00 UTC
        assert result.hour == 13


class TestGetAirportTimezoneName:
    def test_returns_none_for_unknown_airport(self, test_db):
        from backend.timezone_utils import _get_airport_timezone, get_airport_timezone_name

        _get_airport_timezone.cache_clear()
        result = get_airport_timezone_name("ZZZ")
        assert result is None

    def test_returns_timezone_for_known_airport(self, test_db):
        from backend.database import db_write
        from backend.timezone_utils import _get_airport_timezone, get_airport_timezone_name

        _get_airport_timezone.cache_clear()

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('LHR', 'Heathrow', 'London', 'GB', 51.47, -0.46)"
            )

        _get_airport_timezone.cache_clear()
        result = get_airport_timezone_name("LHR")
        assert result == "Europe/London"


class TestApplyAirportTimezones:
    def test_already_utc_flag_just_adds_tz_names(self, test_db):
        from backend.database import db_write
        from backend.timezone_utils import _get_airport_timezone, apply_airport_timezones

        _get_airport_timezone.cache_clear()

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('GRU', 'Guarulhos', 'São Paulo', 'BR', -23.43, -46.47)"
            )
        _get_airport_timezone.cache_clear()

        dep_dt = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        arr_dt = datetime(2025, 6, 1, 14, 0, 0, tzinfo=UTC)
        flight = {
            "_times_already_utc": True,
            "departure_airport": "GRU",
            "arrival_airport": "GRU",
            "departure_datetime": dep_dt,
            "arrival_datetime": arr_dt,
        }
        result = apply_airport_timezones(flight)

        assert "_times_already_utc" not in result
        assert result["departure_datetime"] == dep_dt  # unchanged
        assert "departure_timezone" in result

    def test_converts_naive_datetimes(self, test_db):
        from backend.timezone_utils import apply_airport_timezones

        flight = {
            "departure_airport": "ZZZ",
            "arrival_airport": "ZZZ",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0),
            "arrival_datetime": datetime(2025, 6, 1, 14, 0, 0),
        }
        result = apply_airport_timezones(flight)
        # Should have timezone-aware datetimes now
        assert result["departure_datetime"].tzinfo is not None
        assert result["arrival_datetime"].tzinfo is not None

    def test_strips_utc_label_for_local_times(self, test_db):
        from backend.timezone_utils import apply_airport_timezones

        # UTC-labelled datetimes that are actually local times get stripped
        flight = {
            "departure_airport": "ZZZ",
            "arrival_airport": "ZZZ",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_datetime": datetime(2025, 6, 1, 14, 0, 0, tzinfo=UTC),
        }
        # Should not crash
        result = apply_airport_timezones(flight)
        assert "departure_datetime" in result

    def test_no_airports_no_crash(self, test_db):
        from backend.timezone_utils import apply_airport_timezones

        flight = {
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0),
            "arrival_datetime": datetime(2025, 6, 1, 14, 0, 0),
        }
        result = apply_airport_timezones(flight)
        assert "departure_datetime" in result

    def test_missing_datetimes_ok(self, test_db):
        from backend.timezone_utils import apply_airport_timezones

        flight = {"departure_airport": "GRU", "arrival_airport": "LHR"}
        result = apply_airport_timezones(flight)
        # Should not crash
        assert isinstance(result, dict)
