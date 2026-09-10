"""
Test: Turkish Airlines (TK) ticket-details email parser.

Fixture: tests/fixtures/turkish_ticket_details_anonymized.json
  TK2576 IST→DNZ 21 Sep 2026 06:35→07:40
  TK2331 ADB→IST  2 Oct 2026 17:55→19:20
  Reservation code: TESTRF

The mail is Turkish Airlines' own branded "Ticket Details" template, not a GDS
ticket receipt — the synthetic cases below cover the parts of the layout the one
real fixture does not show (connections, overnight legs, Turkish month names) and
the PDF rendering of the same itinerary.
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _rule():
    return type("Rule", (), {"airline_name": "Turkish Airlines", "airline_code": "TK"})()


def _html(*lines: str) -> str:
    return "<html><body>" + "".join(f"<p>{ln}</p>" for ln in lines) + "</body></html>"


def _email(html: str = "", *, body: str = "", pdf: bool = False):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="turkish-test",
        sender="Turkish Airlines <onlineticket@mail.turkishairlines.com>",
        subject="Turkish Airlines - Ticket Details",
        body=body,
        date=datetime(2026, 8, 19, tzinfo=UTC),
        html_body=html,
        pdf_attachments=[b"%PDF-fake"] if pdf else [],
    )


def _routes(flights):
    return [(f["flight_number"], f["departure_airport"], f["arrival_airport"]) for f in flights]


@pytest.fixture(scope="module")
def turkish_email():
    return load_anonymized_fixture("turkish_ticket_details_anonymized.json")


@pytest.fixture(scope="module")
def turkish_rule(turkish_email):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import match_rule_to_email

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    return match_rule_to_email(turkish_email, rules)


@pytest.fixture(scope="module")
def turkish_flights(turkish_email, turkish_rule, seeded_airports_db):
    from backend.parsers.engine import extract_flights_from_email

    assert turkish_rule is not None, "No rule matched the Turkish Airlines fixture"
    return extract_flights_from_email(turkish_email, turkish_rule)


class TestTurkishRuleMatching:
    def test_rule_found(self, turkish_rule):
        assert turkish_rule is not None

    def test_rule_name(self, turkish_rule):
        assert turkish_rule.airline_name == "Turkish Airlines"

    def test_rule_code(self, turkish_rule):
        assert turkish_rule.airline_code == "TK"

    def test_subject_gate_accepts_ticket_details(self, turkish_email):
        """ "Turkish Airlines - Ticket Details" carries none of the older keywords."""
        import re

        from backend.parsers.builtin_rules import SUBJECT_PATTERN

        assert re.search(SUBJECT_PATTERN, turkish_email.subject, re.IGNORECASE)

    def test_not_a_gds_receipt(self, turkish_email):
        """The branded mail has no ticket-receipt marker, so the GDS parser is out."""
        from backend.parsers.gds_eticket import extract_gds_eticket, looks_like_gds_eticket

        assert not looks_like_gds_eticket(turkish_email.html_body or "")
        assert extract_gds_eticket(turkish_email) == []


class TestTurkishFlightCount:
    def test_two_flights_extracted(self, turkish_flights):
        assert len(turkish_flights) == 2


class TestTurkishOutboundFlight:
    def test_flight_number(self, turkish_flights):
        assert turkish_flights[0]["flight_number"] == "TK2576"

    def test_departure_airport(self, turkish_flights):
        assert turkish_flights[0]["departure_airport"] == "IST"

    def test_arrival_airport(self, turkish_flights):
        assert turkish_flights[0]["arrival_airport"] == "DNZ"

    def test_departure_time(self, turkish_flights):
        assert turkish_flights[0]["departure_datetime"] == dt(2026, 9, 21, 6, 35)

    def test_arrival_time(self, turkish_flights):
        assert turkish_flights[0]["arrival_datetime"] == dt(2026, 9, 21, 7, 40)

    def test_booking_reference(self, turkish_flights):
        assert turkish_flights[0]["booking_reference"] == "TESTRF"

    def test_cabin_class(self, turkish_flights):
        assert turkish_flights[0]["cabin_class"] == "Economy"

    def test_passenger_name(self, turkish_flights):
        """From the greeting — the "Passenger name" heading is followed by routes."""
        assert turkish_flights[0]["passenger_name"] == "TEST PASSENGER"


class TestTurkishReturnFlight:
    def test_flight_number(self, turkish_flights):
        assert turkish_flights[1]["flight_number"] == "TK2331"

    def test_departure_airport(self, turkish_flights):
        assert turkish_flights[1]["departure_airport"] == "ADB"

    def test_arrival_airport(self, turkish_flights):
        assert turkish_flights[1]["arrival_airport"] == "IST"

    def test_departure_time(self, turkish_flights):
        """The return leg takes the date of *its own* header, not the outbound's."""
        assert turkish_flights[1]["departure_datetime"] == dt(2026, 10, 2, 17, 55)

    def test_arrival_time(self, turkish_flights):
        assert turkish_flights[1]["arrival_datetime"] == dt(2026, 10, 2, 19, 20)

    def test_booking_reference(self, turkish_flights):
        assert turkish_flights[1]["booking_reference"] == "TESTRF"


class TestTurkishTransactionDateIgnored:
    """The mail opens with "Transaction date:" — the day the ticket was issued.

    It is the nearest parseable date above the first leg, so a parser that simply
    walked upwards for a date would file every flight on the issue date.
    """

    def test_legs_do_not_use_the_issue_date(self, turkish_flights):
        issue_date = datetime(2026, 8, 19).date()
        assert all(f["departure_datetime"].date() != issue_date for f in turkish_flights)


class TestTurkishConnection:
    """A connection prints two leg blocks under one route header."""

    CONNECTION = _html(
        "Flight details",
        "Istanbul (IST) - Lisbon (LIS)",
        "21 September 2026 Monday",
        "Economy Class (P) - EcoFly",
        "06:35",
        "IST",
        "1 stop",
        "TK1031",
        "09:15",
        "MAD",
        "11:40",
        "MAD",
        "Connecting flight",
        "TK1032",
        "13:05",
        "LIS",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.turkish import extract

        return extract(_email(self.CONNECTION), _rule())

    def test_both_legs_extracted(self, flights):
        assert _routes(flights) == [("TK1031", "IST", "MAD"), ("TK1032", "MAD", "LIS")]

    def test_second_leg_shares_the_header_date(self, flights):
        assert flights[1]["departure_datetime"] == dt(2026, 9, 21, 11, 40)


class TestTurkishOvernightLeg:
    """Only one date is printed per block, so a past-midnight arrival must roll."""

    OVERNIGHT = _html(
        "Flight details",
        "Istanbul (IST) - Stockholm (ARN)",
        "21 September 2026 Monday",
        "Business Class (J) - BusinessFly",
        "22:40",
        "IST",
        "Direct flight",
        "TK1795",
        "01:55",
        "ARN",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.turkish import extract

        return extract(_email(self.OVERNIGHT), _rule())

    def test_arrival_rolls_to_next_day(self, flights):
        assert flights[0]["departure_datetime"] == dt(2026, 9, 21, 22, 40)
        assert flights[0]["arrival_datetime"] == dt(2026, 9, 22, 1, 55)

    def test_cabin_class(self, flights):
        assert flights[0]["cabin_class"] == "Business"


class TestTurkishLanguageItinerary:
    """The same template in Turkish — month names and the cabin label differ."""

    TURKISH = _html(
        "Uçuş detayları",
        "İstanbul (IST) - Lizbon (LIS)",
        "21 Eylül 2026 Pazartesi",
        "Ekonomi Sınıfı (P) - EcoFly",
        "06:35",
        "IST",
        "Aktarmasız uçuş",
        "TK1759",
        "09:55",
        "LIS",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.turkish import extract

        return extract(_email(self.TURKISH), _rule())

    def test_flight_extracted(self, flights):
        assert _routes(flights) == [("TK1759", "IST", "LIS")]

    def test_turkish_month_name_parsed(self, flights):
        assert flights[0]["departure_datetime"] == dt(2026, 9, 21, 6, 35)

    def test_cabin_class(self, flights):
        assert flights[0]["cabin_class"] == "Ekonomi"


class TestTurkishPdfLayout:
    """The PDF attachment restates the itinerary as per-leg detail blocks.

    Exercised on the text pdfplumber produces, which is what the parser consumes;
    building a real PDF would test pdfplumber, not this layout.
    """

    PDF_TEXT = "\n".join(
        [
            "Your ticket has been created. Reservation code",
            "Mr. TEST PASSENGER",
            "TESTRF",
            "Transaction date: 19 August 2026, 21:11 (GMT +03) (Istanbul Local Time)",
            "Flight details",
            "Istanbul (IST) - Denizli (DNZ) 21 September 2026 Monday",
            "06:35 07:40",
            "Direct flight Journey duration",
            "IST DNZ Economy Class (P) - EcoFly",
            "1h 5m",
            "Istanbul Denizli",
            "Flight details",
            "06:35 ISTANBUL (TÜRKİYE) Istanbul Airport (IST)",
            "Airline - Flight no: TURKISH AIRLINES - TK2576",
            "Aircraft type: Narrow-body - Airbus A319-100",
            "07:40 DENİZLİ (TÜRKİYE) Denizli Cardak Airport (DNZ)",
            "Fare Rules",
            "Izmir (ADB) - Istanbul (IST) 2 October 2026 Friday",
            "17:55 19:20",
            "Direct flight Journey duration",
            "ADB IST Economy Class (T) - EcoFly",
            "1h 25m",
            "Izmir Istanbul",
            "Flight details",
            "17:55 IZMİR (TÜRKİYE) Izmir Adnan Menderes Airport (ADB)",
            "Airline - Flight no: TURKISH AIRLINES - TK2331",
            "Aircraft type: Narrow-body - Airbus A321-232",
            "19:20 ISTANBUL (TÜRKİYE) Istanbul Airport (IST)",
        ]
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.turkish import _legs_from_pdf_text

        return _legs_from_pdf_text(self.PDF_TEXT, _rule())

    def test_both_legs_extracted(self, flights):
        assert _routes(flights) == [("TK2576", "IST", "DNZ"), ("TK2331", "ADB", "IST")]

    def test_times(self, flights):
        assert flights[0]["departure_datetime"] == dt(2026, 9, 21, 6, 35)
        assert flights[0]["arrival_datetime"] == dt(2026, 9, 21, 7, 40)
        assert flights[1]["departure_datetime"] == dt(2026, 10, 2, 17, 55)
        assert flights[1]["arrival_datetime"] == dt(2026, 10, 2, 19, 20)

    def test_cabin_class_is_not_the_iata_pair(self, flights):
        """The cabin line reads "IST DNZ Economy Class (P)" in the PDF rendering."""
        assert [f["cabin_class"] for f in flights] == ["Economy", "Economy"]

    def test_arrival_and_next_departure_are_not_paired(self, flights):
        """No flight number sits between one leg's arrival and the next departure."""
        assert len(flights) == 2

    def test_pdf_used_only_when_the_html_yields_nothing(self, seeded_airports_db, monkeypatch):
        from backend.parsers.airlines import turkish

        email_msg = _email(
            "<html><body><p>Your ticket has been created.</p></body></html>", pdf=True
        )
        monkeypatch.setattr(
            type(email_msg),
            "get_pdf_text",
            lambda self: TestTurkishPdfLayout.PDF_TEXT,
            raising=False,
        )
        flights = turkish.extract(email_msg, _rule())
        assert _routes(flights) == [("TK2576", "IST", "DNZ"), ("TK2331", "ADB", "IST")]
        assert flights[0]["booking_reference"] == "TESTRF"


class TestTurkishRejections:
    def test_marketing_mail_yields_nothing(self, seeded_airports_db):
        from backend.parsers.airlines.turkish import extract

        html = _html(
            "Flight details",
            "Istanbul (IST) - Denizli (DNZ)",
            "21 September 2026 Monday",
            "Discover our new destinations",
        )
        assert extract(_email(html), _rule()) == []

    def test_aircraft_type_is_not_taken_for_a_flight_number(self, seeded_airports_db):
        """ "A319" in the block must not become a leg of its own."""
        from backend.parsers.airlines.turkish import extract

        html = _html(
            "Flight details",
            "Istanbul (IST) - Denizli (DNZ)",
            "21 September 2026 Monday",
            "06:35",
            "IST",
            "A319",
            "07:40",
            "DNZ",
        )
        assert extract(_email(html), _rule()) == []

    def test_leg_without_a_header_date_is_dropped(self, seeded_airports_db):
        """Rather than borrowing the issue date from further up the mail."""
        from backend.parsers.airlines.turkish import extract

        html = _html(
            "Transaction date: 19 August 2026, 21:11 (GMT +03) (Istanbul Local Time)",
            "Flight details",
            "Istanbul (IST) - Denizli (DNZ)",
            "Economy Class (P) - EcoFly",
            "06:35",
            "IST",
            "Direct flight",
            "TK2576",
            "07:40",
            "DNZ",
        )
        assert extract(_email(html), _rule()) == []
