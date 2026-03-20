"""Tests for backend.utils shared utilities."""

from datetime import UTC, datetime, timezone, timedelta

import pytest

from backend.utils import (
    now_iso,
    dt_to_iso,
    calc_duration_minutes,
    calc_flight_status,
)


class TestNowIso:
    def test_returns_string(self):
        result = now_iso()
        assert isinstance(result, str)

    def test_contains_utc_offset(self):
        result = now_iso()
        # ISO format with UTC should contain +00:00 or Z
        assert "+00:00" in result or "Z" in result.upper()

    def test_is_close_to_now(self):
        before = datetime.now(UTC)
        result = now_iso()
        after = datetime.now(UTC)
        parsed = datetime.fromisoformat(result)
        assert before <= parsed <= after


class TestDtToIso:
    def test_none_returns_none(self):
        assert dt_to_iso(None) is None

    def test_aware_datetime(self):
        dt = datetime(2025, 6, 1, 10, 30, 0, tzinfo=UTC)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result
        assert "10:30" in result
        assert "+00:00" in result or "UTC" in result

    def test_naive_datetime_assumes_utc(self):
        dt = datetime(2025, 6, 1, 10, 30, 0)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result
        assert "10:30" in result

    def test_non_datetime_falls_back_to_str(self):
        assert dt_to_iso("2025-06-01") == "2025-06-01"

    def test_non_datetime_integer(self):
        assert dt_to_iso(42) == "42"

    def test_non_utc_timezone_preserved(self):
        tz = timezone(timedelta(hours=5))
        dt = datetime(2025, 6, 1, 15, 0, 0, tzinfo=tz)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result
        assert "+05:00" in result


class TestCalcDurationMinutes:
    def test_normal_flight(self):
        dep = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        arr = datetime(2025, 6, 1, 12, 30, 0, tzinfo=UTC)
        assert calc_duration_minutes(dep, arr) == 150

    def test_one_minute_flight(self):
        dep = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        arr = datetime(2025, 6, 1, 10, 1, 0, tzinfo=UTC)
        assert calc_duration_minutes(dep, arr) == 1

    def test_zero_duration_returns_none(self):
        dt = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        assert calc_duration_minutes(dt, dt) is None

    def test_negative_duration_returns_none(self):
        dep = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        arr = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        assert calc_duration_minutes(dep, arr) is None

    def test_none_dep_returns_none(self):
        arr = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        assert calc_duration_minutes(None, arr) is None

    def test_none_arr_returns_none(self):
        dep = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        assert calc_duration_minutes(dep, None) is None

    def test_both_none_returns_none(self):
        assert calc_duration_minutes(None, None) is None

    def test_overnight_flight(self):
        dep = datetime(2025, 6, 1, 22, 0, 0, tzinfo=UTC)
        arr = datetime(2025, 6, 2, 6, 0, 0, tzinfo=UTC)
        assert calc_duration_minutes(dep, arr) == 480


class TestCalcFlightStatus:
    def test_past_arrival_is_completed(self):
        past = datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert calc_flight_status(past) == "completed"

    def test_future_arrival_is_upcoming(self):
        future = datetime(2099, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert calc_flight_status(future) == "upcoming"

    def test_none_arrival_is_upcoming(self):
        assert calc_flight_status(None) == "upcoming"

    def test_naive_past_datetime_treated_as_utc(self):
        past_naive = datetime(2000, 1, 1, 0, 0, 0)
        assert calc_flight_status(past_naive) == "completed"

    def test_naive_future_datetime_treated_as_utc(self):
        future_naive = datetime(2099, 1, 1, 0, 0, 0)
        assert calc_flight_status(future_naive) == "upcoming"
