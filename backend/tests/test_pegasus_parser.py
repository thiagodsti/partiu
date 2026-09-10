"""
Test: Pegasus Airlines (PC) booking-confirmation email parser.

Fixture: tests/fixtures/pegasus_booking_confirmation_anonymized.json
  PC1284 ARN→SAW 19 Sep 2026 02:45→07:20, terminals 5 → MAIN
  PC1279 SAW→ARN  4 Oct 2026 07:25→10:05, terminals MAIN → 5
  PNR No: TESTPC

The mail is Pegasus' own Turkish-language template with no attachment behind it,
so the HTML block is the only rendering there is. The synthetic cases cover the
parts of the layout the one real fixture does not show: a block with no duration
line, a block with no terminals, an overnight leg, and the two ways a leg block
can bleed into its neighbour.
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _rule():
    return type("Rule", (), {"airline_name": "Pegasus Airlines", "airline_code": "PC"})()


def _html(*lines: str) -> str:
    return "<html><body>" + "".join(f"<p>{ln}</p>" for ln in lines) + "</body></html>"


def _email(html: str = "", *, body: str = ""):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="pegasus-test",
        sender="Pegasus <pegasus@flypgs.com>",
        subject="PC1284 İstanbul: Rezervasyonun onaylandı! Biletini görüntüle",
        body=body,
        date=datetime(2026, 8, 19, tzinfo=UTC),
        html_body=html,
        pdf_attachments=[],
    )


def _extract(html: str) -> list[dict]:
    from backend.parsers.airlines import pegasus

    return pegasus.extract(_email(html), _rule())


def _routes(flights):
    return [(f["flight_number"], f["departure_airport"], f["arrival_airport"]) for f in flights]


@pytest.fixture(scope="module")
def pegasus_email():
    return load_anonymized_fixture("pegasus_booking_confirmation_anonymized.json")


@pytest.fixture(scope="module")
def pegasus_rule(pegasus_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(pegasus_email, rules)


@pytest.fixture(scope="module")
def pegasus_flights(pegasus_email, pegasus_rule, seeded_airports_db):
    from backend.parsers.engine import extract_flights_from_email

    assert pegasus_rule is not None, "No rule matched the Pegasus fixture"
    return extract_flights_from_email(pegasus_email, pegasus_rule)


class TestPegasusRuleMatching:
    def test_rule_found(self, pegasus_rule):
        assert pegasus_rule is not None

    def test_rule_name(self, pegasus_rule):
        assert pegasus_rule.airline_name == "Pegasus Airlines"

    def test_rule_code(self, pegasus_rule):
        assert pegasus_rule.airline_code == "PC"

    def test_subject_gate_accepts_turkish_subject(self, pegasus_email):
        """Pegasus subjects are Turkish only: "reserv" does not match "Rezervasyon"."""
        import re

        from backend.parsers.builtin_rules import SUBJECT_PATTERN

        assert re.search(SUBJECT_PATTERN, pegasus_email.subject, re.IGNORECASE)

    def test_subject_gate_accepts_reservation_without_ticket_word(self):
        """A confirmation whose subject drops "Bilet" still has to reach the rule."""
        import re

        from backend.parsers.builtin_rules import SUBJECT_PATTERN

        assert re.search(SUBJECT_PATTERN, "Rezervasyonun onaylandı!", re.IGNORECASE)


class TestPegasusFixture:
    def test_both_legs_found(self, pegasus_flights):
        assert len(pegasus_flights) == 2

    def test_routes(self, pegasus_flights):
        assert _routes(pegasus_flights) == [
            ("PC1284", "ARN", "SAW"),
            ("PC1279", "SAW", "ARN"),
        ]

    def test_outbound_times(self, pegasus_flights):
        out = pegasus_flights[0]
        assert out["departure_datetime"] == dt(2026, 9, 19, 2, 45)
        assert out["arrival_datetime"] == dt(2026, 9, 19, 7, 20)

    def test_return_times(self, pegasus_flights):
        ret = pegasus_flights[1]
        assert ret["departure_datetime"] == dt(2026, 10, 4, 7, 25)
        assert ret["arrival_datetime"] == dt(2026, 10, 4, 10, 5)

    def test_return_leg_is_not_dated_from_the_outbound_header(self, pegasus_flights):
        """Each block takes the date above it, not the first date in the mail."""
        assert pegasus_flights[0]["departure_datetime"].month == 9
        assert pegasus_flights[1]["departure_datetime"].month == 10

    def test_check_in_opening_date_is_not_used(self, pegasus_flights):
        """ "Check-in Açılış: 12 Eylül 2026" sits above the first leg block."""
        assert all(f["departure_datetime"].day != 12 for f in pegasus_flights)

    def test_terminals(self, pegasus_flights):
        assert [(f["departure_terminal"], f["arrival_terminal"]) for f in pegasus_flights] == [
            ("5", "MAIN"),
            ("MAIN", "5"),
        ]

    def test_booking_reference(self, pegasus_flights):
        """ "PNR No:" — the label the shared extractor stopped at before "No"."""
        assert all(f["booking_reference"] == "TESTPC" for f in pegasus_flights)

    def test_passenger_from_greeting(self, pegasus_flights):
        assert all(f["passenger_name"] == "Bob Traveler" for f in pegasus_flights)

    def test_airline_stamped_from_rule(self, pegasus_flights):
        assert all(f["airline_code"] == "PC" for f in pegasus_flights)


class TestPegasusLayoutVariants:
    """Parts of the template the single real fixture does not exercise."""

    def test_block_without_duration_line(self, seeded_airports_db):
        flights = _extract(
            _html(
                "19 Eylül 2026",
                "PC1284",
                "ARN",
                "SAW",
                "Stockholm - Isveç",
                "02:45",
                "Istanbul - Türkiye",
                "07:20",
            )
        )
        assert _routes(flights) == [("PC1284", "ARN", "SAW")]
        assert flights[0]["departure_datetime"] == dt(2026, 9, 19, 2, 45)

    def test_block_without_terminals(self, seeded_airports_db):
        flights = _extract(
            _html(
                "19 Eylül 2026",
                "PC1284",
                "ARN",
                "3sa 35dk",
                "SAW",
                "Stockholm - Isveç",
                "02:45",
                "Istanbul - Türkiye",
                "07:20",
            )
        )
        assert len(flights) == 1
        assert flights[0]["departure_terminal"] == ""
        assert flights[0]["arrival_terminal"] == ""

    def test_overnight_leg_rolls_arrival_forward(self, seeded_airports_db):
        flights = _extract(
            _html(
                "19 Eylül 2026",
                "PC1284",
                "ARN",
                "3sa 35dk",
                "SAW",
                "Stockholm - Isveç",
                "23:30",
                "Istanbul - Türkiye",
                "01:15",
            )
        )
        assert flights[0]["departure_datetime"] == dt(2026, 9, 19, 23, 30)
        assert flights[0]["arrival_datetime"] == dt(2026, 9, 20, 1, 15)

    def test_turkish_month_names_resolve(self, seeded_airports_db):
        """Every leg date in this template is a Turkish month name."""
        flights = _extract(
            _html(
                "04 Ekim 2026",
                "PC1279",
                "SAW",
                "3sa 40dk",
                "ARN",
                "Istanbul - Türkiye",
                "07:25",
                "Stockholm - Isveç",
                "10:05",
            )
        )
        assert flights[0]["departure_datetime"] == dt(2026, 10, 4, 7, 25)


class TestPegasusBlockIsolation:
    """A block must never take a value from the leg after it."""

    def test_truncated_block_does_not_borrow_the_next_leg(self, seeded_airports_db):
        """The first block loses its times; it is dropped, not completed from below."""
        flights = _extract(
            _html(
                "19 Eylül 2026",
                "PC1284",
                "ARN",
                "3sa 35dk",
                "SAW",
                "04 Ekim 2026",
                "PC1279",
                "SAW",
                "3sa 40dk",
                "ARN",
                "Istanbul - Türkiye",
                "07:25",
                "Stockholm - Isveç",
                "10:05",
            )
        )
        assert _routes(flights) == [("PC1279", "SAW", "ARN")]

    def test_date_below_a_block_is_not_used(self, seeded_airports_db):
        """The date is looked for above the flight number only."""
        flights = _extract(
            _html(
                "PC1284",
                "ARN",
                "3sa 35dk",
                "SAW",
                "Stockholm - Isveç",
                "02:45",
                "Istanbul - Türkiye",
                "07:20",
                "19 Eylül 2026",
            )
        )
        assert flights == []

    def test_dated_line_with_a_prefix_is_not_a_header(self, seeded_airports_db):
        """Only a bare date line counts — "Check-in Açılış: …" must not."""
        flights = _extract(
            _html(
                "Check-in Açılış: 12 Eylül 2026 02:45",
                "PC1284",
                "ARN",
                "3sa 35dk",
                "SAW",
                "Stockholm - Isveç",
                "02:45",
                "Istanbul - Türkiye",
                "07:20",
            )
        )
        assert flights == []

    def test_non_pegasus_flight_number_is_not_an_anchor(self, seeded_airports_db):
        """The anchor is pinned to PC: a marketing carrier's number is another airline's leg."""
        flights = _extract(
            _html(
                "19 Eylül 2026",
                "TK1784",
                "ARN",
                "3sa 35dk",
                "SAW",
                "Stockholm - Isveç",
                "02:45",
                "Istanbul - Türkiye",
                "07:20",
            )
        )
        assert flights == []

    def test_unknown_iata_is_dropped_not_guessed(self, seeded_airports_db):
        flights = _extract(
            _html(
                "19 Eylül 2026",
                "PC1284",
                "ARN",
                "3sa 35dk",
                "ZZZ",
                "Stockholm - Isveç",
                "02:45",
                "Nowhere - Nowhere",
                "07:20",
            )
        )
        assert flights == []
