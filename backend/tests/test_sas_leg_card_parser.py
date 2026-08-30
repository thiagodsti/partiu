"""
Test: SAS Scandinavian Airlines "leg card" template parser.

Fixture: tests/fixtures/sas_leg_card_anonymized.eml
  ARN→CDG AF1063 | CDG→PEK AF382 | PEK→AMS KL898 | AMS→ARN KL1227

Newer SAS booking-confirmation template where each leg is a stack of lines
(date/time, city/airport, duration, flight number) with no explicit "A - B"
route text, and all four legs are codeshare flights (Air France / KLM) rather
than SAS-marketed ones. The original dash-route regex in extract_bs4() found
no route matches at all and silently returned zero flights, which caused sync
to fall through to the generic HTML extractor and import unrelated garbage
flights (wrong airports, wrong flight numbers). _extract_leg_card_style()
handles this template directly.
"""

from datetime import UTC, datetime

import pytest
from conftest import load_eml_as_email_message


def dt(year, month, day, hour, minute) -> datetime:
    """UTC-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def sas_leg_card_email():
    return load_eml_as_email_message("sas_leg_card_anonymized.eml")


@pytest.fixture(scope="module")
def sas_leg_card_rule(sas_leg_card_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(sas_leg_card_email, rules)


@pytest.fixture(scope="module")
def sas_leg_card_flights(sas_leg_card_email, sas_leg_card_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert sas_leg_card_rule is not None, "No parsing rule matched the SAS leg-card fixture"
    return extract_flights_from_email(sas_leg_card_email, sas_leg_card_rule)


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


class TestSASLegCardRuleMatching:
    def test_rule_is_found(self, sas_leg_card_rule):
        assert sas_leg_card_rule is not None

    def test_rule_name(self, sas_leg_card_rule):
        assert sas_leg_card_rule.airline_name == "SAS Scandinavian Airlines"


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------


class TestSASLegCardFlightCount:
    def test_flight_count(self, sas_leg_card_flights):
        assert len(sas_leg_card_flights) == 4


# ---------------------------------------------------------------------------
# Leg 1: ARN → CDG  AF1063
# ---------------------------------------------------------------------------


class TestSASLegCardLegOne:
    def test_flight_number(self, sas_leg_card_flights):
        assert sas_leg_card_flights[0]["flight_number"] == "AF1063"

    def test_departure_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[0]["arrival_airport"] == "CDG"

    def test_departure_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[0]["departure_datetime"] == dt(2027, 3, 23, 18, 30)

    def test_arrival_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[0]["arrival_datetime"] == dt(2027, 3, 23, 21, 20)


# ---------------------------------------------------------------------------
# Leg 2: CDG → PEK  AF382
# ---------------------------------------------------------------------------


class TestSASLegCardLegTwo:
    def test_flight_number(self, sas_leg_card_flights):
        assert sas_leg_card_flights[1]["flight_number"] == "AF382"

    def test_departure_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[1]["departure_airport"] == "CDG"

    def test_arrival_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[1]["arrival_airport"] == "PEK"

    def test_departure_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[1]["departure_datetime"] == dt(2027, 3, 23, 23, 20)

    def test_arrival_datetime(self, sas_leg_card_flights):
        # Overnight leg: arrival is the next calendar day.
        assert sas_leg_card_flights[1]["arrival_datetime"] == dt(2027, 3, 24, 17, 40)


# ---------------------------------------------------------------------------
# Leg 3: PEK → AMS  KL898
# ---------------------------------------------------------------------------


class TestSASLegCardLegThree:
    def test_flight_number(self, sas_leg_card_flights):
        assert sas_leg_card_flights[2]["flight_number"] == "KL898"

    def test_departure_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[2]["departure_airport"] == "PEK"

    def test_arrival_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[2]["arrival_airport"] == "AMS"

    def test_departure_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[2]["departure_datetime"] == dt(2027, 4, 8, 10, 55)

    def test_arrival_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[2]["arrival_datetime"] == dt(2027, 4, 8, 17, 20)


# ---------------------------------------------------------------------------
# Leg 4: AMS → ARN  KL1227
# ---------------------------------------------------------------------------


class TestSASLegCardLegFour:
    def test_flight_number(self, sas_leg_card_flights):
        assert sas_leg_card_flights[3]["flight_number"] == "KL1227"

    def test_departure_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[3]["departure_airport"] == "AMS"

    def test_arrival_airport(self, sas_leg_card_flights):
        assert sas_leg_card_flights[3]["arrival_airport"] == "ARN"

    def test_departure_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[3]["departure_datetime"] == dt(2027, 4, 8, 20, 50)

    def test_arrival_datetime(self, sas_leg_card_flights):
        assert sas_leg_card_flights[3]["arrival_datetime"] == dt(2027, 4, 8, 22, 55)


# ---------------------------------------------------------------------------
# Booking reference
# ---------------------------------------------------------------------------


class TestSASLegCardBookingReference:
    def test_booking_reference_value(self, sas_leg_card_flights):
        for f in sas_leg_card_flights:
            assert (f.get("booking_reference") or "").strip() == "ABC123"
