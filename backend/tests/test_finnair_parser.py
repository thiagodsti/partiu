"""
Test: Finnair (AY) e-ticket parser.

Fixture: tests/fixtures/finnair_eticket_anonymized.json
  AY806  ARN→HEL, 29 Jul 2024 07:15→09:15
  AY813  HEL→ARN, 31 Jul 2024 15:55→15:55
  Booking reference: TESTRF (anonymized from TWJRQF)

Year is extracted from subject: "DEP: 29JUL2024" → 2024.

Note: airport city names are anonymized in the fixture; IATA codes are
recovered from the Baggage Policy section (ARNHEL, HELARN).
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def finnair_email():
    return load_anonymized_fixture("finnair_eticket_anonymized.json")


@pytest.fixture(scope="module")
def finnair_rule(finnair_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(finnair_email, rules)


@pytest.fixture(scope="module")
def finnair_flights(finnair_email, finnair_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert finnair_rule is not None, "No rule matched the Finnair fixture"
    return extract_flights_from_email(finnair_email, finnair_rule)


class TestFinnairRuleMatching:
    def test_rule_found(self, finnair_rule):
        assert finnair_rule is not None

    def test_rule_name(self, finnair_rule):
        assert finnair_rule.airline_name == "Finnair"

    def test_rule_code(self, finnair_rule):
        assert finnair_rule.airline_code == "AY"


class TestFinnairFlightCount:
    def test_two_flights_extracted(self, finnair_flights):
        assert len(finnair_flights) == 2


class TestFinnairFlightData:
    def test_first_flight_number(self, finnair_flights):
        assert finnair_flights[0]["flight_number"] == "AY0806"

    def test_first_departure_airport(self, finnair_flights):
        assert finnair_flights[0]["departure_airport"] == "ARN"

    def test_first_arrival_airport(self, finnair_flights):
        assert finnair_flights[0]["arrival_airport"] == "HEL"

    def test_first_departure_datetime(self, finnair_flights):
        assert finnair_flights[0]["departure_datetime"] == dt(2024, 7, 29, 7, 15)

    def test_first_arrival_datetime(self, finnair_flights):
        assert finnair_flights[0]["arrival_datetime"] == dt(2024, 7, 29, 9, 15)

    def test_second_flight_number(self, finnair_flights):
        assert finnair_flights[1]["flight_number"] == "AY0813"

    def test_second_departure_airport(self, finnair_flights):
        assert finnair_flights[1]["departure_airport"] == "HEL"

    def test_second_arrival_airport(self, finnair_flights):
        assert finnair_flights[1]["arrival_airport"] == "ARN"

    def test_second_departure_datetime(self, finnair_flights):
        assert finnair_flights[1]["departure_datetime"] == dt(2024, 7, 31, 15, 55)

    def test_second_arrival_datetime(self, finnair_flights):
        assert finnair_flights[1]["arrival_datetime"] == dt(2024, 7, 31, 15, 55)

    def test_booking_reference(self, finnair_flights):
        # Booking reference is anonymized to "TESTRF" in the fixture
        assert all(f["booking_reference"] == "TESTRF" for f in finnair_flights)
