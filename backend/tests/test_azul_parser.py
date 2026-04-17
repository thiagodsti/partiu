"""
Test: Azul Brazilian Airlines parser.

Fixture: tests/fixtures/azul_anonymized.eml
  VCP → FLN  AD4849
  Booking reference: TQJWFX
"""

from datetime import UTC, datetime

import pytest

from backend.tests.conftest import load_eml_as_email_message


def dt(year, month, day, hour, minute) -> datetime:
    """UTC-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def azul_email():
    return load_eml_as_email_message("azul_anonymized.eml")


@pytest.fixture(scope="module")
def azul_rule(azul_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(azul_email, rules)


@pytest.fixture(scope="module")
def azul_flights(azul_email, azul_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert azul_rule is not None, "No parsing rule matched the Azul fixture"
    return extract_flights_from_email(azul_email, azul_rule)


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


class TestAzulRuleMatching:
    def test_rule_is_found(self, azul_rule):
        assert azul_rule is not None

    def test_rule_name(self, azul_rule):
        assert azul_rule.airline_name == "Azul Brazilian Airlines"

    def test_airline_code(self, azul_rule):
        assert azul_rule.airline_code == "AD"


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------


class TestAzulFlightCount:
    def test_flight_count(self, azul_flights):
        assert len(azul_flights) == 1


# ---------------------------------------------------------------------------
# VCP → FLN  AD4849
# ---------------------------------------------------------------------------


class TestAzulFlightData:
    def test_flight_number(self, azul_flights):
        assert azul_flights[0]["flight_number"] == "AD4849"

    def test_departure_airport(self, azul_flights):
        assert azul_flights[0]["departure_airport"] == "VCP"

    def test_arrival_airport(self, azul_flights):
        assert azul_flights[0]["arrival_airport"] == "FLN"

    def test_departure_datetime(self, azul_flights):
        assert azul_flights[0]["departure_datetime"] == dt(2026, 3, 2, 13, 20)

    def test_arrival_datetime(self, azul_flights):
        assert azul_flights[0]["arrival_datetime"] == dt(2026, 3, 2, 14, 35)

    def test_booking_reference(self, azul_flights):
        assert azul_flights[0]["booking_reference"] == "TQJWFX"


# ---------------------------------------------------------------------------
# Layout B: no-year date + bullet separator + same-line flight number
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def azul2_email():
    return load_eml_as_email_message("azul2_anonymized.eml")


@pytest.fixture(scope="module")
def azul2_flights(azul2_email, azul_rule):
    from backend.parsers.engine import extract_flights_from_email

    return extract_flights_from_email(azul2_email, azul_rule)


class TestAzulLayoutB:
    def test_flight_count(self, azul2_flights):
        assert len(azul2_flights) == 1

    def test_flight_number(self, azul2_flights):
        assert azul2_flights[0]["flight_number"] == "AD4849"

    def test_departure_airport(self, azul2_flights):
        assert azul2_flights[0]["departure_airport"] == "VCP"

    def test_arrival_airport(self, azul2_flights):
        assert azul2_flights[0]["arrival_airport"] == "FLN"

    def test_departure_datetime(self, azul2_flights):
        assert azul2_flights[0]["departure_datetime"] == dt(2026, 3, 2, 13, 20)

    def test_arrival_datetime(self, azul2_flights):
        assert azul2_flights[0]["arrival_datetime"] == dt(2026, 3, 2, 14, 35)

    def test_booking_reference(self, azul2_flights):
        assert azul2_flights[0]["booking_reference"] == "TQJWFX"
