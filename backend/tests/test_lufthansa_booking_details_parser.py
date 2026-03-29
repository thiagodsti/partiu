"""
Test: Lufthansa 'Booking details' email parser (booking.lufthansa.com format).

Fixture: tests/fixtures/lufthansa_booking_details_anonymized.json
  LH809  ARN→FRA  29 Mar 2024  06:45→09:00
  LH104  FRA→MUC  29 Mar 2024  12:15→13:10
  Booking reference: L3TT5J
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def lh_email():
    return load_anonymized_fixture("lufthansa_booking_details_anonymized.json")


@pytest.fixture(scope="module")
def lh_rule(lh_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(lh_email, rules)


@pytest.fixture(scope="module")
def lh_flights(lh_email, lh_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert lh_rule is not None, "No rule matched the Lufthansa booking-details fixture"
    return extract_flights_from_email(lh_email, lh_rule)


class TestLufthansaBookingRuleMatching:
    def test_rule_found(self, lh_rule):
        assert lh_rule is not None

    def test_rule_name(self, lh_rule):
        assert lh_rule.airline_name == "Lufthansa"

    def test_rule_code(self, lh_rule):
        assert lh_rule.airline_code == "LH"


class TestLufthansaBookingFlightCount:
    def test_two_flights_extracted(self, lh_flights):
        assert len(lh_flights) == 2


class TestLufthansaBookingFlight1:
    def test_flight_number(self, lh_flights):
        assert lh_flights[0]["flight_number"] == "LH809"

    def test_departure_airport(self, lh_flights):
        assert lh_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, lh_flights):
        assert lh_flights[0]["arrival_airport"] == "FRA"

    def test_departure_time(self, lh_flights):
        assert lh_flights[0]["departure_datetime"] == dt(2024, 3, 29, 6, 45)

    def test_arrival_time(self, lh_flights):
        assert lh_flights[0]["arrival_datetime"] == dt(2024, 3, 29, 9, 0)

    def test_booking_reference(self, lh_flights):
        assert lh_flights[0]["booking_reference"] == "L3TT5J"


class TestLufthansaBookingFlight2:
    def test_flight_number(self, lh_flights):
        assert lh_flights[1]["flight_number"] == "LH104"

    def test_departure_airport(self, lh_flights):
        assert lh_flights[1]["departure_airport"] == "FRA"

    def test_arrival_airport(self, lh_flights):
        assert lh_flights[1]["arrival_airport"] == "MUC"

    def test_departure_time(self, lh_flights):
        assert lh_flights[1]["departure_datetime"] == dt(2024, 3, 29, 12, 15)

    def test_arrival_time(self, lh_flights):
        assert lh_flights[1]["arrival_datetime"] == dt(2024, 3, 29, 13, 10)


class TestLufthansaBookingSubjectFilter:
    def test_booking_details_subject_matched(self, lh_rule):
        """Regression: 'Booking details' subject was not matched by the Lufthansa rule."""
        assert lh_rule is not None

    def test_subject_pattern_matches_booking_details(self):
        import re

        from backend.parsers.builtin_rules import BUILTIN_AIRLINE_RULES

        lh = next(r for r in BUILTIN_AIRLINE_RULES if r["airline_code"] == "LH")
        pat = re.compile(str(lh["subject_pattern"]), re.IGNORECASE)
        assert pat.search("Booking details | Departure: 29 March 2024 | ARN-MUC")
