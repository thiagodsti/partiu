"""
Test: ITA Airways boarding-pass email parser.

Fixture: tests/fixtures/ita_boarding_pass_anonymized.eml
  AZ2058 FCO→LIN 13 Apr 2025 21:00→22:10
  Booking reference: KKEZ2E
  Seat: 5C
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def ita_email():
    return load_anonymized_fixture("ita_boarding_pass_anonymized.json")


@pytest.fixture(scope="module")
def ita_rule(ita_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(ita_email, rules)


@pytest.fixture(scope="module")
def ita_flights(ita_email, ita_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert ita_rule is not None, "No rule matched the ITA fixture"
    return extract_flights_from_email(ita_email, ita_rule)


class TestITARuleMatching:
    def test_rule_found(self, ita_rule):
        assert ita_rule is not None

    def test_rule_name(self, ita_rule):
        assert ita_rule.airline_name == "ITA Airways"

    def test_rule_code(self, ita_rule):
        assert ita_rule.airline_code == "AZ"


class TestITAFlightCount:
    def test_one_flight_extracted(self, ita_flights):
        assert len(ita_flights) == 1


class TestITAFlightData:
    def test_flight_number(self, ita_flights):
        assert ita_flights[0]["flight_number"] == "AZ2058"

    def test_departure_airport(self, ita_flights):
        assert ita_flights[0]["departure_airport"] == "FCO"

    def test_arrival_airport(self, ita_flights):
        assert ita_flights[0]["arrival_airport"] == "LIN"

    def test_departure_time(self, ita_flights):
        assert ita_flights[0]["departure_datetime"] == dt(2025, 4, 13, 21, 0)

    def test_arrival_time(self, ita_flights):
        assert ita_flights[0]["arrival_datetime"] == dt(2025, 4, 13, 22, 10)

    def test_booking_reference(self, ita_flights):
        assert ita_flights[0]["booking_reference"] == "KKEZ2E"

    def test_seat(self, ita_flights):
        assert ita_flights[0]["seat"] == "5C"
