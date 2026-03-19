"""Tests for backend.parsers.shared utilities."""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup


def make_soup(html: str):
    return BeautifulSoup(html, "html.parser")


class TestGetText:
    def test_none_returns_empty(self):
        from backend.parsers.shared import _get_text

        assert _get_text(None) == ""

    def test_simple_text(self):
        from backend.parsers.shared import _get_text

        tag = make_soup("<p>Hello World</p>").find("p")
        assert _get_text(tag) == "Hello World"

    def test_collapses_whitespace(self):
        from backend.parsers.shared import _get_text

        tag = make_soup("<p>Hello   World\n\nFoo</p>").find("p")
        assert _get_text(tag) == "Hello World Foo"

    def test_nested_tags(self):
        from backend.parsers.shared import _get_text

        tag = make_soup("<div><span>A</span><span>B</span></div>").find("div")
        result = _get_text(tag)
        assert "A" in result and "B" in result

    def test_strips_leading_trailing(self):
        from backend.parsers.shared import _get_text

        tag = make_soup("<p>  trimmed  </p>").find("p")
        assert _get_text(tag) == "trimmed"


class TestMakeAware:
    def test_naive_becomes_utc(self):
        from backend.parsers.shared import _make_aware

        naive = datetime(2024, 1, 15, 10, 30)
        aware = _make_aware(naive)
        assert aware.tzinfo is UTC

    def test_already_aware_is_unchanged(self):
        from backend.parsers.shared import _make_aware

        aware = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        result = _make_aware(aware)
        assert result is aware

    def test_naive_preserves_time(self):
        from backend.parsers.shared import _make_aware

        naive = datetime(2024, 6, 20, 14, 45)
        aware = _make_aware(naive)
        assert aware.hour == 14
        assert aware.minute == 45


class TestBuildDatetime:
    def test_valid_date_and_time(self):
        from backend.parsers.shared import _build_datetime

        d = date(2024, 6, 15)
        result = _build_datetime(d, "14:30")
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30
        assert result.tzinfo is not None

    def test_none_date_returns_none(self):
        from backend.parsers.shared import _build_datetime

        assert _build_datetime(None, "10:00") is None

    def test_empty_time_returns_none(self):
        from backend.parsers.shared import _build_datetime

        assert _build_datetime(date(2024, 1, 1), "") is None

    def test_invalid_time_format_returns_none(self):
        from backend.parsers.shared import _build_datetime

        assert _build_datetime(date(2024, 1, 1), "not-a-time") is None

    def test_midnight(self):
        from backend.parsers.shared import _build_datetime

        result = _build_datetime(date(2024, 3, 10), "00:00")
        assert result is not None
        assert result.hour == 0
        assert result.minute == 0


class TestMakeFlightDict:
    def _rule(self):
        rule = MagicMock()
        rule.airline_name = "Test Air"
        rule.airline_code = "TA"
        return rule

    def test_all_fields_present(self):
        from backend.parsers.shared import _make_flight_dict

        dep = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        arr = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        result = _make_flight_dict(
            self._rule(), "TA123", "GRU", "EZE", dep, arr, "ABC123", "John Doe"
        )
        assert result is not None
        assert result["flight_number"] == "TA123"
        assert result["departure_airport"] == "GRU"
        assert result["arrival_airport"] == "EZE"
        assert result["booking_reference"] == "ABC123"
        assert result["passenger_name"] == "John Doe"
        assert result["airline_name"] == "Test Air"
        assert result["airline_code"] == "TA"

    def test_contains_optional_empty_fields(self):
        from backend.parsers.shared import _make_flight_dict

        dep = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        arr = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        result = _make_flight_dict(self._rule(), "TA123", "GRU", "EZE", dep, arr)
        assert result["seat"] == ""
        assert result["cabin_class"] == ""

    def test_missing_flight_number_returns_none(self):
        from backend.parsers.shared import _make_flight_dict

        dep = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        arr = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        assert _make_flight_dict(self._rule(), "", "GRU", "EZE", dep, arr) is None

    def test_missing_departure_airport_returns_none(self):
        from backend.parsers.shared import _make_flight_dict

        dep = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        arr = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        assert _make_flight_dict(self._rule(), "TA123", "", "EZE", dep, arr) is None

    def test_missing_arrival_airport_returns_none(self):
        from backend.parsers.shared import _make_flight_dict

        dep = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        arr = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        assert _make_flight_dict(self._rule(), "TA123", "GRU", "", dep, arr) is None

    def test_missing_dep_dt_returns_none(self):
        from backend.parsers.shared import _make_flight_dict

        arr = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        assert _make_flight_dict(self._rule(), "TA123", "GRU", "EZE", None, arr) is None

    def test_missing_arr_dt_returns_none(self):
        from backend.parsers.shared import _make_flight_dict

        dep = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        assert _make_flight_dict(self._rule(), "TA123", "GRU", "EZE", dep, None) is None


class TestExtractBookingReference:
    def test_from_subject_booking_ref(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>Some content</p>")
        result = _extract_booking_reference(soup, subject="Booking ref: ABCD123")
        assert result == "ABCD123"

    def test_from_body_pnr(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>PNR: XYZ456</p>")
        result = _extract_booking_reference(soup)
        assert result == "XYZ456"

    def test_from_body_codigo_de_reserva(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>Código de reserva: LATAM7</p>")
        result = _extract_booking_reference(soup)
        assert result == "LATAM7"

    def test_from_body_reserva(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>Reserva: QWERTY</p>")
        result = _extract_booking_reference(soup)
        assert result == "QWERTY"

    def test_booking_colon_format(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>Booking: BOOK99</p>")
        result = _extract_booking_reference(soup)
        assert result == "BOOK99"

    def test_no_ref_returns_empty(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>Nothing here at all</p>")
        assert _extract_booking_reference(soup) == ""

    def test_confirmation_code(self):
        from backend.parsers.shared import _extract_booking_reference

        soup = make_soup("<p>Confirmation code: CONF12</p>")
        result = _extract_booking_reference(soup)
        assert result == "CONF12"


class TestExtractPassengerName:
    def test_passenger_name_label(self):
        from backend.parsers.shared import _extract_passenger_name

        soup = make_soup("<p>Passenger name: John Smith</p>")
        result = _extract_passenger_name(soup)
        assert "John" in result

    def test_hello_greeting(self):
        from backend.parsers.shared import _extract_passenger_name

        soup = make_soup("<p>Hello Maria</p>")
        result = _extract_passenger_name(soup)
        assert result == "Maria"

    def test_ola_greeting(self):
        from backend.parsers.shared import _extract_passenger_name

        soup = make_soup("<p>Olá Carlos</p>")
        result = _extract_passenger_name(soup)
        assert result == "Carlos"

    def test_hola_greeting(self):
        from backend.parsers.shared import _extract_passenger_name

        soup = make_soup("<p>Hola Pedro</p>")
        result = _extract_passenger_name(soup)
        assert result == "Pedro"

    def test_no_name_returns_empty(self):
        from backend.parsers.shared import _extract_passenger_name

        soup = make_soup("<p>No passenger info here at all</p>")
        assert _extract_passenger_name(soup) == ""

    def test_passenger_list_pattern(self):
        from backend.parsers.shared import _extract_passenger_name

        soup = make_soup("<p>Lista de passageiros - Anna Costa</p>")
        result = _extract_passenger_name(soup)
        assert "Anna" in result


class TestAirportDistance:
    def test_unknown_airports_returns_fallback(self, test_db):
        from backend.parsers.shared import _airport_distance

        result = _airport_distance("XXX", "YYY")
        assert result == 1.0

    def test_known_airports_returns_distance(self, test_db):
        from backend.database import db_write
        from backend.parsers.shared import _airport_distance

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, latitude, longitude) VALUES (?, ?, ?, ?)",
                ("ORG", "Origin Airport", 0.0, 0.0),
            )
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, latitude, longitude) VALUES (?, ?, ?, ?)",
                ("DST", "Dest Airport", 10.0, 10.0),
            )
        result = _airport_distance("ORG", "DST")
        assert result > 0.0

    def test_same_coordinates_near_zero(self, test_db):
        from backend.database import db_write
        from backend.parsers.shared import _airport_distance

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, latitude, longitude) VALUES (?, ?, ?, ?)",
                ("SA1", "Same A", 10.0, 20.0),
            )
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, latitude, longitude) VALUES (?, ?, ?, ?)",
                ("SA2", "Same B", 10.0, 20.0),
            )
        result = _airport_distance("SA1", "SA2")
        assert result < 0.1

    def test_db_exception_returns_fallback(self, test_db):
        from backend.parsers.shared import _airport_distance

        with patch("backend.database.db_conn", side_effect=Exception("DB error")):
            result = _airport_distance("GRU", "EZE")
        assert result == 1.0
