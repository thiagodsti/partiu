"""
Test: Brussels Airlines (SN) parser.

Fixture: tests/fixtures/brussels.eml
  Round trip: ARN→BRU→OLB (SN2298 + SN3107) and OLB→BRU→ARN (SN3108 + SN2297)
  Booking reference: 8EOVNP

The fixture sender is anonymised (From: bob.test@example.com), so rule
matching is tested via direct extractor invocation rather than the engine's
match_rule_to_email path.  The sender pattern brusselsairlines.com will
match real emails from booking@information.brusselsairlines.com.
"""

from datetime import UTC, datetime

import pytest

from backend.tests.conftest import load_eml_as_email_message


def dt(year, month, day, hour, minute) -> datetime:
    """UTC-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def brussels_email():
    return load_eml_as_email_message("brussels.eml")


@pytest.fixture(scope="module")
def brussels_rule():
    from backend.parsers.builtin_rules import get_builtin_rules

    return next(r for r in get_builtin_rules() if r.airline_code == "SN")


@pytest.fixture(scope="module")
def brussels_flights(brussels_email, brussels_rule):
    from backend.parsers.airlines.brussels_airlines import extract

    return extract(brussels_email, brussels_rule)


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesFlightCount:
    def test_flight_count(self, brussels_flights):
        assert len(brussels_flights) == 4


# ---------------------------------------------------------------------------
# Leg 1: ARN → BRU  SN2298
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesLeg1:
    def test_flight_number(self, brussels_flights):
        assert brussels_flights[0]["flight_number"] == "SN2298"

    def test_departure_airport(self, brussels_flights):
        assert brussels_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, brussels_flights):
        assert brussels_flights[0]["arrival_airport"] == "BRU"

    def test_departure_datetime(self, brussels_flights):
        assert brussels_flights[0]["departure_datetime"] == dt(2026, 7, 3, 6, 30)

    def test_arrival_datetime(self, brussels_flights):
        assert brussels_flights[0]["arrival_datetime"] == dt(2026, 7, 3, 8, 45)

    def test_airline_code(self, brussels_flights):
        assert brussels_flights[0]["airline_code"] == "SN"

    def test_cabin_class(self, brussels_flights):
        assert "Economy" in brussels_flights[0]["cabin_class"]


# ---------------------------------------------------------------------------
# Leg 2: BRU → OLB  SN3107
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesLeg2:
    def test_flight_number(self, brussels_flights):
        assert brussels_flights[1]["flight_number"] == "SN3107"

    def test_departure_airport(self, brussels_flights):
        assert brussels_flights[1]["departure_airport"] == "BRU"

    def test_arrival_airport(self, brussels_flights):
        assert brussels_flights[1]["arrival_airport"] == "OLB"

    def test_departure_datetime(self, brussels_flights):
        assert brussels_flights[1]["departure_datetime"] == dt(2026, 7, 3, 10, 50)

    def test_arrival_datetime(self, brussels_flights):
        assert brussels_flights[1]["arrival_datetime"] == dt(2026, 7, 3, 13, 0)


# ---------------------------------------------------------------------------
# Leg 3: OLB → BRU  SN3108
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesLeg3:
    def test_flight_number(self, brussels_flights):
        assert brussels_flights[2]["flight_number"] == "SN3108"

    def test_departure_airport(self, brussels_flights):
        assert brussels_flights[2]["departure_airport"] == "OLB"

    def test_arrival_airport(self, brussels_flights):
        assert brussels_flights[2]["arrival_airport"] == "BRU"

    def test_departure_datetime(self, brussels_flights):
        assert brussels_flights[2]["departure_datetime"] == dt(2026, 7, 10, 13, 50)

    def test_arrival_datetime(self, brussels_flights):
        assert brussels_flights[2]["arrival_datetime"] == dt(2026, 7, 10, 15, 55)


# ---------------------------------------------------------------------------
# Leg 4: BRU → ARN  SN2297
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesLeg4:
    def test_flight_number(self, brussels_flights):
        assert brussels_flights[3]["flight_number"] == "SN2297"

    def test_departure_airport(self, brussels_flights):
        assert brussels_flights[3]["departure_airport"] == "BRU"

    def test_arrival_airport(self, brussels_flights):
        assert brussels_flights[3]["arrival_airport"] == "ARN"

    def test_departure_datetime(self, brussels_flights):
        assert brussels_flights[3]["departure_datetime"] == dt(2026, 7, 10, 21, 0)

    def test_arrival_datetime(self, brussels_flights):
        assert brussels_flights[3]["arrival_datetime"] == dt(2026, 7, 10, 23, 10)


# ---------------------------------------------------------------------------
# Booking reference (shared across all legs)
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesBookingReference:
    def test_booking_reference_present(self, brussels_flights):
        for f in brussels_flights:
            assert (f.get("booking_reference") or "").strip() != ""

    def test_booking_reference_value(self, brussels_flights):
        for f in brussels_flights:
            assert f.get("booking_reference") == "8EOVNP"


# ---------------------------------------------------------------------------
# Rule registration
# ---------------------------------------------------------------------------


class TestBrusselsAirlinesRule:
    def test_rule_name(self, brussels_rule):
        assert brussels_rule.airline_name == "Brussels Airlines"

    def test_rule_code(self, brussels_rule):
        assert brussels_rule.airline_code == "SN"

    def test_extractor_callable(self, brussels_rule):
        assert callable(brussels_rule.extractor)
