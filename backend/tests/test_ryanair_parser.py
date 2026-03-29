"""
Test: Ryanair travel itinerary email parser.

Fixture: tests/fixtures/ryanair_itinerary_anonymized.json
  FR2878 BGY→ARN 23 Apr 2025 17:55→20:35
  Booking reference: K1QU3R
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def ryanair_email():
    return load_anonymized_fixture("ryanair_itinerary_anonymized.json")


@pytest.fixture(scope="module")
def ryanair_rule(ryanair_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(ryanair_email, rules)


@pytest.fixture(scope="module")
def ryanair_flights(ryanair_email, ryanair_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert ryanair_rule is not None, "No rule matched the Ryanair fixture"
    return extract_flights_from_email(ryanair_email, ryanair_rule)


class TestRyanairRuleMatching:
    def test_rule_found(self, ryanair_rule):
        assert ryanair_rule is not None

    def test_rule_name(self, ryanair_rule):
        assert ryanair_rule.airline_name == "Ryanair"

    def test_rule_code(self, ryanair_rule):
        assert ryanair_rule.airline_code == "FR"


class TestRyanairFlightCount:
    def test_one_flight_extracted(self, ryanair_flights):
        assert len(ryanair_flights) == 1


class TestRyanairFlightData:
    def test_flight_number(self, ryanair_flights):
        assert ryanair_flights[0]["flight_number"] == "FR2878"

    def test_departure_airport(self, ryanair_flights):
        assert ryanair_flights[0]["departure_airport"] == "BGY"

    def test_arrival_airport(self, ryanair_flights):
        assert ryanair_flights[0]["arrival_airport"] == "ARN"

    def test_departure_time(self, ryanair_flights):
        assert ryanair_flights[0]["departure_datetime"] == dt(2025, 4, 23, 17, 55)

    def test_arrival_time(self, ryanair_flights):
        assert ryanair_flights[0]["arrival_datetime"] == dt(2025, 4, 23, 20, 35)

    def test_booking_reference(self, ryanair_flights):
        assert ryanair_flights[0]["booking_reference"] == "K1QU3R"


class TestSubjectKeywordFix:
    def test_itinerary_subject_is_fetched(self):
        """Regression: 'Ryanair Travel Itinerary' was silently skipped due to \\b bug."""
        from backend.parsers.email_connector import _matches_flight_filter

        assert _matches_flight_filter("Itinerary@ryanair.com", "Ryanair Travel Itinerary", None)

    def test_reservation_subject_is_fetched(self):
        from backend.parsers.email_connector import _matches_flight_filter

        assert _matches_flight_filter("no-reply@airline.com", "Your reservation details", None)
