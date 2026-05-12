"""
Test: Iberia (IB) booking confirmation email parser.

Fixture: tests/fixtures/iberia_booking_confirmation_anonymized.json
  IB0828 ARN→MAD 17 Sep 2026 18:35→22:40
  IB0823 MAD→ARN 20 Sep 2026 10:15→14:10
  Booking reference: TESTRF
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def iberia_email():
    return load_anonymized_fixture("iberia_booking_confirmation_anonymized.json")


@pytest.fixture(scope="module")
def iberia_rule(iberia_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(iberia_email, rules)


@pytest.fixture(scope="module")
def iberia_flights(iberia_email, iberia_rule, seeded_airports_db):
    from backend.parsers.engine import extract_flights_from_email

    assert iberia_rule is not None, "No rule matched the Iberia fixture"
    return extract_flights_from_email(iberia_email, iberia_rule)


class TestIberiaRuleMatching:
    def test_rule_found(self, iberia_rule):
        assert iberia_rule is not None

    def test_rule_name(self, iberia_rule):
        assert iberia_rule.airline_name == "Iberia"

    def test_rule_code(self, iberia_rule):
        assert iberia_rule.airline_code == "IB"


class TestIberiaFlightCount:
    def test_two_flights_extracted(self, iberia_flights):
        assert len(iberia_flights) == 2


class TestIberiaOutwardFlight:
    def test_flight_number(self, iberia_flights):
        assert iberia_flights[0]["flight_number"] == "IB0828"

    def test_departure_airport(self, iberia_flights):
        assert iberia_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, iberia_flights):
        assert iberia_flights[0]["arrival_airport"] == "MAD"

    def test_departure_time(self, iberia_flights):
        assert iberia_flights[0]["departure_datetime"] == dt(2026, 9, 17, 18, 35)

    def test_arrival_time(self, iberia_flights):
        assert iberia_flights[0]["arrival_datetime"] == dt(2026, 9, 17, 22, 40)

    def test_booking_reference(self, iberia_flights):
        assert iberia_flights[0]["booking_reference"] == "TESTRF"


class TestIberiaReturnFlight:
    def test_flight_number(self, iberia_flights):
        assert iberia_flights[1]["flight_number"] == "IB0823"

    def test_departure_airport(self, iberia_flights):
        assert iberia_flights[1]["departure_airport"] == "MAD"

    def test_arrival_airport(self, iberia_flights):
        assert iberia_flights[1]["arrival_airport"] == "ARN"

    def test_departure_time(self, iberia_flights):
        assert iberia_flights[1]["departure_datetime"] == dt(2026, 9, 20, 10, 15)

    def test_arrival_time(self, iberia_flights):
        assert iberia_flights[1]["arrival_datetime"] == dt(2026, 9, 20, 14, 10)

    def test_booking_reference(self, iberia_flights):
        assert iberia_flights[1]["booking_reference"] == "TESTRF"
