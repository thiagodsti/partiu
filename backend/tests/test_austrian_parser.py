"""
Test: Austrian Airlines (OS) parsers.

Fixture: tests/fixtures/austrian_boarding_pass_anonymized.json
  OS317 VIE→ARN, 03 Apr 2024 20:25 → 22:35
  Booking reference: RHFNEJ
  Seat: 23F

Fixture: tests/fixtures/austrian_booking_confirmation_anonymized.json
  The "Thank you for booking with us" HTML confirmation, as one <p> per visible
  text line (the layout the extractor reads is html_to_text's, and this is that
  text verbatim, scrubbed). Unread until now — so the OS318 leg its later
  cancellation names was never stored.
  OS318 ARN→VIE, 29 Mar 2024 06:35 → 08:50, terminals 5 → 3
  OS317 VIE→ARN, 03 Apr 2024 20:25 → 22:35, terminals 3 → 5
  Booking reference: TESTRF

Fixture: tests/fixtures/austrian_rebooking_confirmation_anonymized.json
  "Your Travel Confirmation" after a rebooking: a plain-text table whose From
  and To cells print as one phrase, "Vienna Intl Stockholm".
  OS317 VIE→ARN, 03 Apr 2024 20:25 → 22:35, terminals 3 → 5
  Booking reference: TESTRF; passenger DOE / JOHN MR
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def austrian_email():
    return load_anonymized_fixture("austrian_boarding_pass_anonymized.json")


@pytest.fixture(scope="module")
def austrian_rule(austrian_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(austrian_email, rules)


@pytest.fixture(scope="module")
def austrian_flights(austrian_email, austrian_rule, seeded_airports_db):
    from backend.parsers.engine import extract_flights_from_email

    assert austrian_rule is not None, "No rule matched the Austrian Airlines fixture"
    return extract_flights_from_email(austrian_email, austrian_rule)


class TestAustrianRuleMatching:
    def test_rule_found(self, austrian_rule):
        assert austrian_rule is not None

    def test_rule_name(self, austrian_rule):
        assert austrian_rule.airline_name == "Austrian Airlines"

    def test_rule_code(self, austrian_rule):
        assert austrian_rule.airline_code == "OS"


class TestAustrianFlightCount:
    def test_one_flight_extracted(self, austrian_flights):
        assert len(austrian_flights) == 1


class TestAustrianFlightData:
    def test_flight_number(self, austrian_flights):
        assert austrian_flights[0]["flight_number"] == "OS317"

    def test_departure_airport(self, austrian_flights):
        assert austrian_flights[0]["departure_airport"] == "VIE"

    def test_arrival_airport(self, austrian_flights):
        assert austrian_flights[0]["arrival_airport"] == "ARN"

    def test_departure_datetime(self, austrian_flights):
        assert austrian_flights[0]["departure_datetime"] == dt(2024, 4, 3, 20, 25)

    def test_arrival_datetime(self, austrian_flights):
        assert austrian_flights[0]["arrival_datetime"] == dt(2024, 4, 3, 22, 35)

    def test_booking_reference(self, austrian_flights):
        assert austrian_flights[0]["booking_reference"] == "RHFNEJ"

    def test_seat(self, austrian_flights):
        assert austrian_flights[0]["seat"] == "23F"


# ---------------------------------------------------------------------------
# Booking confirmation ("Thank you for booking with us")
# ---------------------------------------------------------------------------


def _flights_for(fixture_name: str):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import extract_flights_from_email, match_rule_to_email

    email = load_anonymized_fixture(fixture_name)
    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    rule = match_rule_to_email(email, rules)
    assert rule is not None and rule.airline_code == "OS"
    return extract_flights_from_email(email, rule)


@pytest.fixture(scope="module")
def booking_flights(seeded_airports_db):
    return _flights_for("austrian_booking_confirmation_anonymized.json")


class TestAustrianBookingConfirmation:
    def test_both_legs(self, booking_flights):
        assert [
            (f["flight_number"], f["departure_airport"], f["arrival_airport"])
            for f in booking_flights
        ] == [
            ("OS318", "ARN", "VIE"),
            ("OS317", "VIE", "ARN"),
        ]

    def test_times_come_from_the_details_block(self, booking_flights):
        # The overview prints only the departure time; the arrival is in the
        # per-leg "Itinerary details" block.
        assert booking_flights[0]["departure_datetime"] == dt(2024, 3, 29, 6, 35)
        assert booking_flights[0]["arrival_datetime"] == dt(2024, 3, 29, 8, 50)
        assert booking_flights[1]["departure_datetime"] == dt(2024, 4, 3, 20, 25)
        assert booking_flights[1]["arrival_datetime"] == dt(2024, 4, 3, 22, 35)

    def test_terminals(self, booking_flights):
        assert (
            booking_flights[0]["departure_terminal"],
            booking_flights[0]["arrival_terminal"],
        ) == ("5", "3")
        assert (
            booking_flights[1]["departure_terminal"],
            booking_flights[1]["arrival_terminal"],
        ) == ("3", "5")

    def test_booking_reference(self, booking_flights):
        assert {f["booking_reference"] for f in booking_flights} == {"TESTRF"}

    def test_the_overview_never_reaches_the_checkin_pattern(self, seeded_airports_db):
        """The check-in regex sees "ARN / VIE … OS317" in the overview — the
        outbound route with the *return* flight number. A "dd Mon yy" date
        anywhere in the text would let it emit that leg; the booking reader
        must win before it runs."""
        from backend.parsers.airlines.austrian import extract
        from backend.parsers.email_connector import EmailMessage

        email = load_anonymized_fixture("austrian_booking_confirmation_anonymized.json")
        poisoned = EmailMessage(
            message_id="x",
            sender=email.sender,
            subject=email.subject,
            body=email.body + "\nIssued 05 Mar 24\n",
            date=email.date,
            html_body=email.html_body,
        )
        rule = type("Rule", (), {"airline_name": "Austrian Airlines", "airline_code": "OS"})()
        assert [(f["flight_number"], f["departure_airport"]) for f in extract(poisoned, rule)] == [
            ("OS318", "ARN"),
            ("OS317", "VIE"),
        ]


# ---------------------------------------------------------------------------
# Rebooking / "Your Travel Confirmation" table
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rebooking_flights(seeded_airports_db):
    return _flights_for("austrian_rebooking_confirmation_anonymized.json")


class TestAustrianRebookingConfirmation:
    def test_one_leg(self, rebooking_flights):
        assert len(rebooking_flights) == 1
        f = rebooking_flights[0]
        assert f["flight_number"] == "OS317"
        assert (f["departure_airport"], f["arrival_airport"]) == ("VIE", "ARN")
        assert f["departure_datetime"] == dt(2024, 4, 3, 20, 25)
        assert f["arrival_datetime"] == dt(2024, 4, 3, 22, 35)

    def test_terminals_and_reference(self, rebooking_flights):
        f = rebooking_flights[0]
        assert (f["departure_terminal"], f["arrival_terminal"]) == ("3", "5")
        assert f["booking_reference"] == "TESTRF"

    def test_passenger_from_the_name_line(self, rebooking_flights):
        assert rebooking_flights[0]["passenger_name"] == "John Doe"


class TestConfirmationRowSplit:
    """The From/To cells print as one phrase; splitting it must never guess."""

    def test_splits_after_an_airport_suffix(self, monkeypatch):
        from backend.parsers.airlines import austrian

        seen = []
        monkeypatch.setattr(
            austrian,
            "resolve_iata",
            lambda n: seen.append(n) or {"Vienna Intl": "VIE", "Stockholm": "ARN"}.get(n, ""),
        )
        assert austrian._route_from_confirmation_row(
            "03 Apr 24, Vienna Intl Stockholm Economy Light,"
        ) == ("VIE", "ARN")
        # "Intl Stockholm" (which resolves to Västerås in real data) is never tried
        assert "Intl Stockholm" not in seen

    def test_without_a_suffix_every_split_must_agree(self, monkeypatch):
        from backend.parsers.airlines import austrian

        table = {"Vienna": "VIE", "Stockholm": "ARN", "Vienna Stockholm": ""}
        monkeypatch.setattr(austrian, "resolve_iata", lambda n: table.get(n, ""))
        assert austrian._route_from_confirmation_row("Vienna Stockholm Economy") == ("VIE", "ARN")

    def test_disagreeing_splits_yield_nothing(self, monkeypatch):
        from backend.parsers.airlines import austrian

        # Two ways to cut the phrase, two different answers: refuse rather than pick.
        table = {
            "Paris": "CDG",
            "Charles De Gaulle Vienna": "VIE",
            "Paris Charles": "CDG",
            "De Gaulle Vienna": "VST",
        }
        monkeypatch.setattr(austrian, "resolve_iata", lambda n: table.get(n, ""))
        assert austrian._route_from_confirmation_row("Paris Charles De Gaulle Vienna Economy") == (
            "",
            "",
        )
