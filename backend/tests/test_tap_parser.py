"""
Test: TAP Air Portugal (TP) flight parser.

Fixtures:
  tap_checkin_anonymized.json
    TP781 ARN→LIS, 01 Feb 2024 14:20→17:45
    Booking reference: TESTRF (anonymized)

  tap_boarding_pass_anonymized.json
    TP82  GRU→LIS, 23 Feb 2024 16:20 → 24 Feb 2024 05:15
    TP780 LIS→ARN, 24 Feb 2024 08:05 → 24 Feb 2024 13:30
    Booking reference: P6ANPW (in HTML microdata)
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Check-in email fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tap_checkin_email():
    return load_anonymized_fixture("tap_checkin_anonymized.json")


@pytest.fixture(scope="module")
def tap_checkin_rule(tap_checkin_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(tap_checkin_email, rules)


@pytest.fixture(scope="module")
def tap_checkin_flights(tap_checkin_email, tap_checkin_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert tap_checkin_rule is not None, "No rule matched the TAP check-in fixture"
    return extract_flights_from_email(tap_checkin_email, tap_checkin_rule)


class TestTAPCheckinRuleMatching:
    def test_rule_found(self, tap_checkin_rule):
        assert tap_checkin_rule is not None

    def test_rule_name(self, tap_checkin_rule):
        assert tap_checkin_rule.airline_name == "TAP Air Portugal"

    def test_rule_code(self, tap_checkin_rule):
        assert tap_checkin_rule.airline_code == "TP"


class TestTAPCheckinFlightCount:
    def test_one_flight_extracted(self, tap_checkin_flights):
        assert len(tap_checkin_flights) == 1


class TestTAPCheckinFlightData:
    def test_flight_number(self, tap_checkin_flights):
        assert tap_checkin_flights[0]["flight_number"] == "TP781"

    def test_departure_airport(self, tap_checkin_flights):
        assert tap_checkin_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, tap_checkin_flights):
        assert tap_checkin_flights[0]["arrival_airport"] == "LIS"

    def test_departure_datetime(self, tap_checkin_flights):
        assert tap_checkin_flights[0]["departure_datetime"] == dt(2024, 2, 1, 14, 20)

    def test_arrival_datetime(self, tap_checkin_flights):
        assert tap_checkin_flights[0]["arrival_datetime"] == dt(2024, 2, 1, 17, 45)

    def test_booking_reference(self, tap_checkin_flights):
        # Booking reference is anonymized to "TESTRF" in the fixture
        assert tap_checkin_flights[0]["booking_reference"] == "TESTRF"


# ---------------------------------------------------------------------------
# Boarding pass email fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tap_bp_email():
    return load_anonymized_fixture("tap_boarding_pass_anonymized.json")


@pytest.fixture(scope="module")
def tap_bp_rule(tap_bp_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(tap_bp_email, rules)


@pytest.fixture(scope="module")
def tap_bp_flights(tap_bp_email, tap_bp_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert tap_bp_rule is not None, "No rule matched the TAP boarding pass fixture"
    return extract_flights_from_email(tap_bp_email, tap_bp_rule)


class TestTAPBoardingPassRuleMatching:
    def test_rule_found(self, tap_bp_rule):
        assert tap_bp_rule is not None

    def test_rule_name(self, tap_bp_rule):
        assert tap_bp_rule.airline_name == "TAP Air Portugal"


class TestTAPBoardingPassFlightCount:
    def test_two_flights_extracted(self, tap_bp_flights):
        assert len(tap_bp_flights) == 2


class TestTAPBoardingPassFlightData:
    def test_first_flight_number(self, tap_bp_flights):
        assert tap_bp_flights[0]["flight_number"] == "TP82"

    def test_first_departure_airport(self, tap_bp_flights):
        assert tap_bp_flights[0]["departure_airport"] == "GRU"

    def test_first_arrival_airport(self, tap_bp_flights):
        assert tap_bp_flights[0]["arrival_airport"] == "LIS"

    def test_first_departure_datetime(self, tap_bp_flights):
        assert tap_bp_flights[0]["departure_datetime"] == dt(2024, 2, 23, 16, 20)

    def test_first_arrival_datetime(self, tap_bp_flights):
        assert tap_bp_flights[0]["arrival_datetime"] == dt(2024, 2, 24, 5, 15)

    def test_second_flight_number(self, tap_bp_flights):
        assert tap_bp_flights[1]["flight_number"] == "TP780"

    def test_second_departure_airport(self, tap_bp_flights):
        assert tap_bp_flights[1]["departure_airport"] == "LIS"

    def test_second_arrival_airport(self, tap_bp_flights):
        assert tap_bp_flights[1]["arrival_airport"] == "ARN"

    def test_second_departure_datetime(self, tap_bp_flights):
        assert tap_bp_flights[1]["departure_datetime"] == dt(2024, 2, 24, 8, 5)

    def test_second_arrival_datetime(self, tap_bp_flights):
        assert tap_bp_flights[1]["arrival_datetime"] == dt(2024, 2, 24, 13, 30)

    def test_booking_reference(self, tap_bp_flights):
        assert all(f["booking_reference"] == "P6ANPW" for f in tap_bp_flights)
