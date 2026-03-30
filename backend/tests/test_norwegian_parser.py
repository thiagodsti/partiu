"""
Test: Norwegian Air Shuttle "Travel documents" email parser.

Fixture: tests/fixtures/norwegian_travel_docs_anonymized.json
  DY4371  ARN→CTA  14 Aug 2019  17:10→20:45
  DY4372  CTA→ARN  24 Aug 2019  14:45→18:25
  Booking reference: QAJV6E
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def norwegian_airports_db(tmp_path_factory):
    """Temporary DB seeded with airports needed for the Norwegian fixture."""
    import backend.config as cfg_module
    import backend.database as db_module

    db_path = str(tmp_path_factory.mktemp("norwegian_airports_db") / "test.db")
    original_path = db_module.settings.DB_PATH

    db_module.settings.DB_PATH = db_path
    cfg_module.settings.DB_PATH = db_path

    from backend.database import db_write, init_database

    init_database()

    airports = [
        ("ARN", "Stockholm Arlanda Airport", "Stockholm", "SE"),
        ("CTA", "Catania-Fontanarossa Airport", "Catania", "IT"),
        ("OSL", "Oslo Gardermoen Airport", "Oslo", "NO"),
        ("CPH", "Copenhagen Airport", "Copenhagen", "DK"),
        ("LHR", "London Heathrow Airport", "London", "GB"),
    ]
    with db_write() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code)"
            " VALUES (?, ?, ?, ?)",
            airports,
        )

    yield db_path

    db_module.settings.DB_PATH = original_path
    cfg_module.settings.DB_PATH = original_path


@pytest.fixture(scope="module")
def norwegian_email():
    return load_anonymized_fixture("norwegian_travel_docs_anonymized.json")


@pytest.fixture(scope="module")
def norwegian_rule(norwegian_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(norwegian_email, rules)


@pytest.fixture(scope="module")
def norwegian_flights(norwegian_email, norwegian_rule, norwegian_airports_db):
    from backend.parsers.engine import extract_flights_from_email

    assert norwegian_rule is not None, "No rule matched the Norwegian fixture"
    return extract_flights_from_email(norwegian_email, norwegian_rule)


# ---------------------------------------------------------------------------
# Rule matching
# ---------------------------------------------------------------------------


class TestNorwegianRuleMatching:
    def test_rule_found(self, norwegian_rule):
        assert norwegian_rule is not None

    def test_rule_airline_name(self, norwegian_rule):
        assert norwegian_rule.airline_name == "Norwegian Air Shuttle"

    def test_rule_airline_code(self, norwegian_rule):
        assert norwegian_rule.airline_code == "DY"


# ---------------------------------------------------------------------------
# Flight count
# ---------------------------------------------------------------------------


class TestNorwegianFlightCount:
    def test_two_flights_extracted(self, norwegian_flights):
        assert len(norwegian_flights) == 2


# ---------------------------------------------------------------------------
# Leg 1: DY4371  ARN → CTA  14 Aug 2019  17:10 → 20:45
# ---------------------------------------------------------------------------


class TestNorwegianLegOne:
    def test_flight_number(self, norwegian_flights):
        assert norwegian_flights[0]["flight_number"] == "DY4371"

    def test_departure_airport(self, norwegian_flights):
        assert norwegian_flights[0]["departure_airport"] == "ARN"

    def test_arrival_airport(self, norwegian_flights):
        assert norwegian_flights[0]["arrival_airport"] == "CTA"

    def test_departure_datetime(self, norwegian_flights):
        assert norwegian_flights[0]["departure_datetime"] == dt(2019, 8, 14, 17, 10)

    def test_arrival_datetime(self, norwegian_flights):
        assert norwegian_flights[0]["arrival_datetime"] == dt(2019, 8, 14, 20, 45)

    def test_booking_reference(self, norwegian_flights):
        assert norwegian_flights[0]["booking_reference"] == "QAJV6E"

    def test_airline_code(self, norwegian_flights):
        assert norwegian_flights[0]["airline_code"] == "DY"


# ---------------------------------------------------------------------------
# Leg 2: DY4372  CTA → ARN  24 Aug 2019  14:45 → 18:25
# ---------------------------------------------------------------------------


class TestNorwegianLegTwo:
    def test_flight_number(self, norwegian_flights):
        assert norwegian_flights[1]["flight_number"] == "DY4372"

    def test_departure_airport(self, norwegian_flights):
        assert norwegian_flights[1]["departure_airport"] == "CTA"

    def test_arrival_airport(self, norwegian_flights):
        assert norwegian_flights[1]["arrival_airport"] == "ARN"

    def test_departure_datetime(self, norwegian_flights):
        assert norwegian_flights[1]["departure_datetime"] == dt(2019, 8, 24, 14, 45)

    def test_arrival_datetime(self, norwegian_flights):
        assert norwegian_flights[1]["arrival_datetime"] == dt(2019, 8, 24, 18, 25)

    def test_booking_reference(self, norwegian_flights):
        assert norwegian_flights[1]["booking_reference"] == "QAJV6E"

    def test_airline_code(self, norwegian_flights):
        assert norwegian_flights[1]["airline_code"] == "DY"


# ---------------------------------------------------------------------------
# Unit tests for _extract_travel_documents directly
# ---------------------------------------------------------------------------


class TestTravelDocumentsExtractorDirect:
    """Test the travel-documents extractor in isolation (no DB needed)."""

    def _make_email(self, body: str):
        from datetime import UTC, datetime

        from backend.parsers.email_connector import EmailMessage

        return EmailMessage(
            message_id="test-direct",
            sender="noreply@norwegian.com",
            subject="Travel documents Ref. QAJV6E",
            body=body,
            date=datetime(2019, 8, 8, tzinfo=UTC),
            html_body="",
            pdf_attachments=[],
        )

    def test_returns_empty_when_no_marker(self, norwegian_rule):
        from backend.parsers.airlines.norwegian import _extract_travel_documents

        email_msg = self._make_email("Some random body with no marker")
        assert _extract_travel_documents(email_msg, norwegian_rule) == []

    def test_detects_travel_documents_format(self, norwegian_rule):
        from backend.parsers.airlines.norwegian import _extract_travel_documents

        email_msg = self._make_email("YOUR BOOKING REFERENCE IS:\nQAJV6E\n")
        # No flights but marker is detected — returns empty list, not raises
        result = _extract_travel_documents(email_msg, norwegian_rule)
        assert isinstance(result, list)

    def test_collapse_body_strips_trailing_whitespace(self):
        from backend.parsers.airlines.norwegian import _collapse_body

        body = "line1   \nline2\n\n\nline3\n"
        result = _collapse_body(body)
        assert "line1   " not in result
        assert "line1\n" in result
        # Multiple blank lines collapsed to one
        assert "\n\n\n" not in result
