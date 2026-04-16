"""
Test: Wizz Air parser.

Fixture: tests/fixtures/wizz_anonymized.eml
  BCN→LTN W95362

Forwarded Gmail itinerary confirmation (wizzair.com sender in body).
"""

from datetime import UTC, datetime

import pytest

from backend.tests.conftest import load_eml_as_email_message


def dt(year, month, day, hour, minute) -> datetime:
    """UTC-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def wizz_email():
    return load_eml_as_email_message("wizz_anonymized.eml")


@pytest.fixture(scope="module")
def wizz_rule(wizz_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(wizz_email, rules)


@pytest.fixture(scope="module")
def wizz_flights(wizz_email, wizz_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert wizz_rule is not None, "No parsing rule matched the Wizz Air fixture"
    return extract_flights_from_email(wizz_email, wizz_rule)


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


class TestWizzAirRuleMatching:
    def test_rule_is_found(self, wizz_rule):
        assert wizz_rule is not None

    def test_rule_name(self, wizz_rule):
        assert wizz_rule.airline_name == "Wizz Air"


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------


class TestWizzAirFlightCount:
    def test_flight_count(self, wizz_flights):
        assert len(wizz_flights) == 1


# ---------------------------------------------------------------------------
# Leg 1: BCN → LTN  W95362
# ---------------------------------------------------------------------------


class TestWizzAirLegOne:
    def test_flight_number(self, wizz_flights):
        assert wizz_flights[0]["flight_number"] == "W95362"

    def test_departure_airport(self, wizz_flights):
        assert wizz_flights[0]["departure_airport"] == "BCN"

    def test_arrival_airport(self, wizz_flights):
        assert wizz_flights[0]["arrival_airport"] == "LTN"

    def test_airline_code(self, wizz_flights):
        assert wizz_flights[0]["airline_code"] == "W6"

    def test_departure_datetime(self, wizz_flights):
        assert wizz_flights[0]["departure_datetime"] == dt(2026, 5, 14, 9, 35)

    def test_arrival_datetime(self, wizz_flights):
        assert wizz_flights[0]["arrival_datetime"] == dt(2026, 5, 14, 11, 0)


# ---------------------------------------------------------------------------
# Booking reference
# ---------------------------------------------------------------------------


class TestWizzAirBookingReference:
    def test_booking_reference_present(self, wizz_flights):
        for f in wizz_flights:
            assert (f.get("booking_reference") or "").strip() != ""

    def test_booking_reference_value(self, wizz_flights):
        for f in wizz_flights:
            assert (f.get("booking_reference") or "").strip() == "GW8PSD"
