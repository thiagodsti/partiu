"""
Test: Kiwi.com forwarded e-ticket (PDF-based) parser.

Fixture: tests/fixtures/kiwi_forwarded_anonymized.eml
  A Gmail forward of a Kiwi.com e-ticket for a 4-leg itinerary:
    ARN → GDN  (FR4678, Ryanair,    Thu 14 May 2026 06:35–07:55)
    GDN → STN  (FR532,  Ryanair,    Thu 14 May 2026 09:00–10:15)
    STN → OSL  (RK1392, Ryanair UK, Sun 17 May 2026 05:55–09:00)
    OSL → ARN  (SK864,  SAS,        Sun 17 May 2026 10:05–11:05)

The email was forwarded from a personal Gmail address, so the outer From header
is not @kiwi.com.  The parser must resolve the rule via forwarded-sender
detection (scanning the email body for "From: … @kiwi.com").
"""
from datetime import datetime, timezone

import pytest

from conftest import load_eml_as_email_message


def dt(year, month, day, hour, minute) -> datetime:
    """UTC-aware datetime helper."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def kiwi_email():
    return load_eml_as_email_message("kiwi_forwarded_anonymized.eml")


@pytest.fixture(scope="module")
def kiwi_rule(kiwi_email):
    from backend.parsers.engine import match_rule_to_email
    from backend.parsers.builtin_rules import get_builtin_rules

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(kiwi_email, rules)


@pytest.fixture(scope="module")
def kiwi_flights(kiwi_email, kiwi_rule):
    from backend.parsers.engine import extract_flights_from_email

    assert kiwi_rule is not None, "No parsing rule matched the Kiwi.com fixture"
    return extract_flights_from_email(kiwi_email, kiwi_rule)


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------

class TestKiwiRuleMatching:
    def test_rule_is_found(self, kiwi_rule):
        assert kiwi_rule is not None

    def test_rule_name_is_kiwi(self, kiwi_rule):
        assert kiwi_rule.airline_name == "Kiwi.com"

    def test_custom_extractor_is_kiwi(self, kiwi_rule):
        assert kiwi_rule.custom_extractor == "kiwi"

    def test_outer_from_is_not_kiwi(self, kiwi_email):
        """Pre-condition: the envelope sender is a personal address, not kiwi.com."""
        assert "kiwi.com" not in kiwi_email.sender.lower(), (
            "Test expectation wrong: outer From should be a personal Gmail address"
        )

    def test_forwarded_sender_detection(self, kiwi_email, kiwi_rule):
        """Rule must be resolved via forwarded-body sender detection, not From header."""
        assert kiwi_rule is not None, (
            "Parser failed to detect Kiwi.com sender inside forwarded email body"
        )


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------

class TestKiwiFlightCount:
    def test_four_flights_extracted(self, kiwi_flights):
        assert len(kiwi_flights) == 4, (
            f"Expected 4 flights, got {len(kiwi_flights)}: "
            + str([f["flight_number"] for f in kiwi_flights])
        )


# ---------------------------------------------------------------------------
# Leg 1: ARN → GDN  FR4678  Ryanair  Thu 14 May 2026
# ---------------------------------------------------------------------------

class TestKiwiLeg1:
    def test_flight_number(self, kiwi_flights):
        assert kiwi_flights[0]["flight_number"] == "FR4678"

    def test_departure_airport(self, kiwi_flights):
        assert kiwi_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, kiwi_flights):
        assert kiwi_flights[0]["arrival_airport"] == "GDN"

    def test_airline_code(self, kiwi_flights):
        assert kiwi_flights[0]["airline_code"] == "FR"

    def test_airline_name(self, kiwi_flights):
        assert kiwi_flights[0]["airline_name"] == "Ryanair"

    def test_departure_datetime(self, kiwi_flights):
        assert kiwi_flights[0]["departure_datetime"] == dt(2026, 5, 14, 6, 35)

    def test_arrival_datetime(self, kiwi_flights):
        assert kiwi_flights[0]["arrival_datetime"] == dt(2026, 5, 14, 7, 55)


# ---------------------------------------------------------------------------
# Leg 2: GDN → STN  FR532  Ryanair  Thu 14 May 2026
# ---------------------------------------------------------------------------

class TestKiwiLeg2:
    def test_flight_number(self, kiwi_flights):
        assert kiwi_flights[1]["flight_number"] == "FR532"

    def test_departure_airport(self, kiwi_flights):
        assert kiwi_flights[1]["departure_airport"] == "GDN"

    def test_arrival_airport(self, kiwi_flights):
        assert kiwi_flights[1]["arrival_airport"] == "STN"

    def test_airline_code(self, kiwi_flights):
        assert kiwi_flights[1]["airline_code"] == "FR"

    def test_airline_name(self, kiwi_flights):
        assert kiwi_flights[1]["airline_name"] == "Ryanair"

    def test_departure_datetime(self, kiwi_flights):
        assert kiwi_flights[1]["departure_datetime"] == dt(2026, 5, 14, 9, 0)

    def test_arrival_datetime(self, kiwi_flights):
        assert kiwi_flights[1]["arrival_datetime"] == dt(2026, 5, 14, 10, 15)


# ---------------------------------------------------------------------------
# Leg 3: STN → OSL  RK1392  Ryanair UK  Sun 17 May 2026
# ---------------------------------------------------------------------------

class TestKiwiLeg3:
    def test_flight_number(self, kiwi_flights):
        assert kiwi_flights[2]["flight_number"] == "RK1392"

    def test_departure_airport(self, kiwi_flights):
        assert kiwi_flights[2]["departure_airport"] == "STN"

    def test_arrival_airport(self, kiwi_flights):
        assert kiwi_flights[2]["arrival_airport"] == "OSL"

    def test_airline_code(self, kiwi_flights):
        assert kiwi_flights[2]["airline_code"] == "RK"

    def test_airline_name(self, kiwi_flights):
        assert kiwi_flights[2]["airline_name"] == "Ryanair UK"

    def test_departure_datetime(self, kiwi_flights):
        assert kiwi_flights[2]["departure_datetime"] == dt(2026, 5, 17, 5, 55)

    def test_arrival_datetime(self, kiwi_flights):
        assert kiwi_flights[2]["arrival_datetime"] == dt(2026, 5, 17, 9, 0)


# ---------------------------------------------------------------------------
# Leg 4: OSL → ARN  SK864  SAS  Sun 17 May 2026
# ---------------------------------------------------------------------------

class TestKiwiLeg4:
    def test_flight_number(self, kiwi_flights):
        assert kiwi_flights[3]["flight_number"] == "SK864"

    def test_departure_airport(self, kiwi_flights):
        assert kiwi_flights[3]["departure_airport"] == "OSL"

    def test_arrival_airport(self, kiwi_flights):
        assert kiwi_flights[3]["arrival_airport"] == "ARN"

    def test_airline_code(self, kiwi_flights):
        assert kiwi_flights[3]["airline_code"] == "SK"

    def test_airline_name(self, kiwi_flights):
        assert kiwi_flights[3]["airline_name"] == "SAS"

    def test_departure_datetime(self, kiwi_flights):
        assert kiwi_flights[3]["departure_datetime"] == dt(2026, 5, 17, 10, 5)

    def test_arrival_datetime(self, kiwi_flights):
        assert kiwi_flights[3]["arrival_datetime"] == dt(2026, 5, 17, 11, 5)


# ---------------------------------------------------------------------------
# Booking reference
# ---------------------------------------------------------------------------

class TestKiwiBookingReference:
    def test_booking_reference_present_on_all_legs(self, kiwi_flights):
        for f in kiwi_flights:
            ref = (f.get("booking_reference") or "").strip()
            assert ref != "", f"Missing booking_reference on {f['flight_number']}"

    def test_booking_reference_value(self, kiwi_flights):
        for f in kiwi_flights:
            assert (f.get("booking_reference") or "").strip() == "755885086"
