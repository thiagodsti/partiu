"""
Test: British Airways e-ticket parser.

Fixture: tests/fixtures/ba_eticket_anonymized.eml
  BA0781 ARN→LHR 23 Dec 2024 | BA0247 LHR→GRU 23 Dec 2024
  IB0268 GRU→MAD 24 Jan 2025 | IB0823 MAD→ARN 25 Jan 2025
  Booking reference: J9CRT8
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def ba_email():
    return load_anonymized_fixture("ba_eticket_anonymized.json")


@pytest.fixture(scope="module")
def ba_rule(ba_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(ba_email, rules)


@pytest.fixture(scope="module")
def ba_flights(ba_email, ba_rule, seeded_airports_db):
    from backend.parsers.engine import extract_flights_from_email

    assert ba_rule is not None, "No rule matched the BA fixture"
    return extract_flights_from_email(ba_email, ba_rule)


class TestBARuleMatching:
    def test_rule_found(self, ba_rule):
        assert ba_rule is not None

    def test_rule_name(self, ba_rule):
        assert ba_rule.airline_name == "British Airways"

    def test_rule_code(self, ba_rule):
        assert ba_rule.airline_code == "BA"


class TestBAFlightCount:
    def test_four_flights_extracted(self, ba_flights):
        assert len(ba_flights) == 4


class TestBAFlightData:
    def test_first_flight_number(self, ba_flights):
        assert ba_flights[0]["flight_number"] == "BA0781"

    def test_first_departure_airport(self, ba_flights):
        assert ba_flights[0]["departure_airport"] == "ARN"

    def test_first_arrival_airport(self, ba_flights):
        assert ba_flights[0]["arrival_airport"] == "LHR"

    def test_first_departure_time(self, ba_flights):
        assert ba_flights[0]["departure_datetime"] == dt(2024, 12, 23, 17, 55)

    def test_first_arrival_time(self, ba_flights):
        assert ba_flights[0]["arrival_datetime"] == dt(2024, 12, 23, 19, 40)

    def test_second_flight_number(self, ba_flights):
        assert ba_flights[1]["flight_number"] == "BA0247"

    def test_second_departure_airport(self, ba_flights):
        assert ba_flights[1]["departure_airport"] == "LHR"

    def test_second_arrival_airport(self, ba_flights):
        assert ba_flights[1]["arrival_airport"] == "GRU"

    def test_third_flight_number(self, ba_flights):
        assert ba_flights[2]["flight_number"] == "IB0268"

    def test_third_departure_airport(self, ba_flights):
        assert ba_flights[2]["departure_airport"] == "GRU"

    def test_third_arrival_airport(self, ba_flights):
        assert ba_flights[2]["arrival_airport"] == "MAD"

    def test_fourth_flight_number(self, ba_flights):
        assert ba_flights[3]["flight_number"] == "IB0823"

    def test_fourth_route(self, ba_flights):
        assert ba_flights[3]["departure_airport"] == "MAD"
        assert ba_flights[3]["arrival_airport"] == "ARN"

    def test_booking_reference(self, ba_flights):
        assert all(f["booking_reference"] == "J9CRT8" for f in ba_flights)
