"""
Test: SAS Scandinavian Airlines parser.

Fixture: tests/fixtures/sas_connection_anonymized.eml
  ARN→LHR SK533  |  LHR→JNB VS449

# TODO: describe the fixture briefly (forwarded? direct? PDF?)
"""

from datetime import UTC, datetime

import pytest
from conftest import load_eml_as_email_message


def dt(year, month, day, hour, minute) -> datetime:
    """UTC-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def sas_scandinavian_airlines_email():
    return load_eml_as_email_message("sas_connection_anonymized.eml")


@pytest.fixture(scope="module")
def sas_scandinavian_airlines_rule(sas_scandinavian_airlines_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(sas_scandinavian_airlines_email, rules)


@pytest.fixture(scope="module")
def sas_scandinavian_airlines_flights(
    sas_scandinavian_airlines_email, sas_scandinavian_airlines_rule
):
    from backend.parsers.engine import extract_flights_from_email

    assert sas_scandinavian_airlines_rule is not None, (
        "No parsing rule matched the SAS Scandinavian Airlines fixture"
    )
    return extract_flights_from_email(
        sas_scandinavian_airlines_email, sas_scandinavian_airlines_rule
    )


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


class TestSASScandinavianAirlinesRuleMatching:
    def test_rule_is_found(self, sas_scandinavian_airlines_rule):
        assert sas_scandinavian_airlines_rule is not None

    def test_rule_name(self, sas_scandinavian_airlines_rule):
        assert sas_scandinavian_airlines_rule.airline_name == "SAS Scandinavian Airlines"


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------


class TestSASScandinavianAirlinesFlightCount:
    def test_flight_count(self, sas_scandinavian_airlines_flights):
        assert len(sas_scandinavian_airlines_flights) == 2


# ---------------------------------------------------------------------------
# Leg 1: ARN → LHR  SK533
# ---------------------------------------------------------------------------


class TestSASScandinavianAirlinesLegOne:
    def test_flight_number(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[0]["flight_number"] == "SK533"

    def test_departure_airport(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[0]["arrival_airport"] == "LHR"

    def test_airline_code(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[0]["airline_code"] == "SK"

    def test_departure_datetime(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[0]["departure_datetime"] == dt(
            2025, 10, 28, 18, 10
        )

    def test_arrival_datetime(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[0]["arrival_datetime"] == dt(2025, 10, 28, 19, 55)


# ---------------------------------------------------------------------------
# Leg 2: LHR → JNB  VS449
# ---------------------------------------------------------------------------


class TestSASScandinavianAirlinesLegTwo:
    def test_flight_number(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[1]["flight_number"] == "VS449"

    def test_departure_airport(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[1]["departure_airport"] == "LHR"

    def test_arrival_airport(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[1]["arrival_airport"] == "JNB"

    def test_airline_code(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[1]["airline_code"] == "SK"

    def test_departure_datetime(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[1]["departure_datetime"] == dt(
            2025, 10, 28, 22, 30
        )

    def test_arrival_datetime(self, sas_scandinavian_airlines_flights):
        assert sas_scandinavian_airlines_flights[1]["arrival_datetime"] == dt(2025, 10, 29, 11, 30)


# ---------------------------------------------------------------------------
# Booking reference
# ---------------------------------------------------------------------------


class TestSASScandinavianAirlinesBookingReference:
    def test_booking_reference(self, sas_scandinavian_airlines_flights):
        for f in sas_scandinavian_airlines_flights:
            assert (f.get("booking_reference") or "").strip() != ""

    def test_booking_reference_value(self, sas_scandinavian_airlines_flights):
        for f in sas_scandinavian_airlines_flights:
            assert (f.get("booking_reference") or "").strip() == "WD7WYD"
