"""
Test: Austrian Airlines (OS) boarding-pass parser.

Fixture: tests/fixtures/austrian_boarding_pass_anonymized.json
  OS317 VIE→ARN, 03 Apr 2024 20:25 → 22:35
  Booking reference: RHFNEJ
  Seat: 23F
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def austrian_email():
    return load_anonymized_fixture("austrian_boarding_pass_anonymized.json")


@pytest.fixture(scope="module")
def austrian_rule(austrian_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(austrian_email, rules)


@pytest.fixture(scope="module")
def austrian_flights(austrian_email, austrian_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert austrian_rule is not None, "No rule matched the Austrian Airlines fixture"
    return extract_flights_from_email(austrian_email, austrian_rule)


class TestAustrianRuleMatching:
    def test_rule_found(self, austrian_rule):
        assert austrian_rule is not None

    def test_rule_name(self, austrian_rule):
        assert austrian_rule.airline_name == "Austrian Airlines"

    def test_rule_code(self, austrian_rule):
        assert austrian_rule.airline_code == "OS"


class TestAustrianFlightCount:
    def test_one_flight_extracted(self, austrian_flights):
        assert len(austrian_flights) == 1


class TestAustrianFlightData:
    def test_flight_number(self, austrian_flights):
        assert austrian_flights[0]["flight_number"] == "OS317"

    def test_departure_airport(self, austrian_flights):
        assert austrian_flights[0]["departure_airport"] == "VIE"

    def test_arrival_airport(self, austrian_flights):
        assert austrian_flights[0]["arrival_airport"] == "ARN"

    def test_departure_datetime(self, austrian_flights):
        assert austrian_flights[0]["departure_datetime"] == dt(2024, 4, 3, 20, 25)

    def test_arrival_datetime(self, austrian_flights):
        assert austrian_flights[0]["arrival_datetime"] == dt(2024, 4, 3, 22, 35)

    def test_booking_reference(self, austrian_flights):
        assert austrian_flights[0]["booking_reference"] == "RHFNEJ"

    def test_seat(self, austrian_flights):
        assert austrian_flights[0]["seat"] == "23F"
