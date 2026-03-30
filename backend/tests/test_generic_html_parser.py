"""
Tests for the generic HTML flight extractor (backend/parsers/generic_html.py).

The generic parser is a pre-LLM fallback for emails without a matched rule or
whose custom extractor returns nothing. It anchors on flight number tokens and
searches a surrounding window for IATA codes, times, and dates.

All airports used in tests must exist in the seeded_airports_db fixture
(ARN, LHR, GRU, MAD, VIE, FCO, CPH, OSL, HEL, GIG, VCP).
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from backend.parsers.email_connector import EmailMessage
from backend.parsers.generic_html import extract_generic_html


def _msg(html: str, subject: str = "", date: datetime | None = None) -> EmailMessage:
    return EmailMessage(
        message_id="test-generic",
        sender="test@example.com",
        subject=subject,
        body="",
        date=date or datetime(2026, 4, 1, tzinfo=UTC),
        html_body=html,
        pdf_attachments=[],
    )


def _html(*lines: str) -> str:
    """Wrap lines in minimal HTML so BeautifulSoup sees them on separate lines."""
    body = "".join(f"<p>{ln}</p>" for ln in lines)
    return f"<html><body>{body}</body></html>"


class TestNoHtmlBody:
    def test_empty_html_returns_empty(self, seeded_airports_db):
        assert extract_generic_html(_msg("")) == []

    def test_no_html_body_returns_empty(self, seeded_airports_db):
        msg = EmailMessage(
            message_id="x",
            sender="",
            subject="",
            body="",
            date=datetime.now(UTC),
            html_body=None,
            pdf_attachments=[],
        )
        assert extract_generic_html(msg) == []


class TestFlightExtraction:
    """Happy-path extraction from common HTML structures."""

    def test_austrian_style_iata_after_fn(self, seeded_airports_db):
        """Flight# then dep IATA then arr IATA, date before flight#."""
        html = _html("03APR26", "OS317", "VIE", "ARN", "14:00", "15:55")
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1
        f = flights[0]
        assert f["flight_number"] == "OS317"
        assert f["departure_airport"] == "VIE"
        assert f["arrival_airport"] == "ARN"

    def test_inline_paren_iata_codes(self, seeded_airports_db):
        """Parenthetical IATA codes like (VIE) and (OSL) are extracted."""
        html = _html(
            "OS311",
            "Vienna -",
            "Oslo",
            "23 Apr 2026",
            "10:00",
            "12:30",
            "(VIE)",
            "(OSL)",
        )
        flights = extract_generic_html(_msg(html))
        assert len(flights) >= 1
        f = flights[0]
        assert f["flight_number"] == "OS311"
        assert f["departure_airport"] in ("VIE", "OSL")

    def test_booking_ref_from_html(self, seeded_airports_db):
        html = _html(
            "Booking Reference: ABC123",
            "LH803",
            "ARN",
            "OSL",
            "14 Jan 2026",
            "14:00",
            "16:05",
        )
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1
        assert flights[0]["booking_reference"] == "ABC123"

    def test_booking_ref_from_subject(self, seeded_airports_db):
        html = _html("SK533", "ARN", "LHR", "28 Oct 2025", "18:10", "19:55")
        msg = _msg(html, subject="Booking Reference: WD7WYD")
        flights = extract_generic_html(msg)
        assert len(flights) == 1
        assert flights[0]["booking_reference"] == "WD7WYD"

    def test_fix_overnight(self, seeded_airports_db):
        """Arrival before departure on same date should add one day."""
        html = _html("VS449", "LHR", "MAD", "28 Oct 2025", "22:30", "11:30")
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1
        assert flights[0]["arrival_datetime"] > flights[0]["departure_datetime"]

    def test_multiple_legs(self, seeded_airports_db):
        """Two flight numbers in the same email produce two legs."""
        html = _html(
            "SK533",
            "ARN",
            "LHR",
            "14 Jan 2026",
            "14:00",
            "16:05",
            "SK534",
            "LHR",
            "ARN",
            "16 Jan 2026",
            "09:00",
            "11:10",
        )
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 2
        assert flights[0]["flight_number"] == "SK533"
        assert flights[1]["flight_number"] == "SK534"

    def test_rule_overrides_airline_code(self, seeded_airports_db):
        """When a rule is provided, airline_name and airline_code come from the rule."""
        rule = MagicMock()
        rule.airline_name = "SAS"
        rule.airline_code = "SK"
        html = _html("SK533", "ARN", "LHR", "14 Jan 2026", "14:00", "16:05")
        flights = extract_generic_html(_msg(html), rule=rule)
        assert len(flights) == 1
        assert flights[0]["airline_name"] == "SAS"
        assert flights[0]["airline_code"] == "SK"

    def test_airline_code_inferred_from_fn_when_no_rule(self, seeded_airports_db):
        """Without a rule, airline_code is inferred from the flight number prefix."""
        html = _html("DY4371", "ARN", "OSL", "14 Aug 2026", "17:10", "18:25")
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1
        assert flights[0]["airline_code"] == "DY"

    def test_compound_time_date_line(self, seeded_airports_db):
        """ITA-style '21:00 - 13 Apr 2025' lines yield both time and date."""
        html = _html("GRU", "GIG", "21:00 - 13 Apr 2025", "AZ2058", "22:10 - 13 Apr 2025")
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1
        f = flights[0]
        assert f["flight_number"] == "AZ2058"
        assert f["departure_airport"] == "GRU"
        assert f["arrival_airport"] == "GIG"
        assert f["departure_datetime"].hour == 21
        assert f["arrival_datetime"].hour == 22

    def test_compound_date_time_line(self, seeded_airports_db):
        """Austrian-style '03.04.2026 - 20:25' lines yield both date and time."""
        html = _html("03.04.2026 - 20:25", "OS317", "VIE", "ARN", "03.04.2026 - 22:00")
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1
        f = flights[0]
        assert f["flight_number"] == "OS317"
        assert f["departure_airport"] == "VIE"
        assert f["arrival_airport"] == "ARN"

    def test_compact_line_format(self, seeded_airports_db):
        """SAS-style compact single-line format: 'SK 533 / 14JAN2026 city - city time time'."""
        from datetime import UTC, datetime

        from backend.parsers.email_connector import EmailMessage

        msg = EmailMessage(
            message_id="test-compact",
            sender="test@example.com",
            subject="",
            body="SK 533 / 14JAN2026 Stockholm Arlanda - Copenhagen 14:00 15:30",
            html_body=None,
            date=datetime(2026, 1, 14, tzinfo=UTC),
            pdf_attachments=[],
        )
        flights = extract_generic_html(msg)
        assert len(flights) == 1
        f = flights[0]
        assert f["flight_number"] == "SK533"
        assert f["departure_airport"] == "ARN"
        assert f["arrival_airport"] == "CPH"

    def test_zero_width_chars_stripped(self, seeded_airports_db):
        """Times with zero-width spaces (Lufthansa style) are parsed correctly."""
        html = _html(
            "16\u200b:\u200b05",  # broken time with ZW spaces — stripped to 16:05
            "LH803",
            "ARN",
            "LHR",
            "18:10",
        )
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1

    def test_plain_text_body_fallback(self, seeded_airports_db):
        """When html_body is None, the plain-text body is used as fallback."""
        from datetime import UTC, datetime

        from backend.parsers.email_connector import EmailMessage

        msg = EmailMessage(
            message_id="test-textfallback",
            sender="test@example.com",
            subject="",
            body="\n".join(
                ["DY4371", "-", "14 Jan 2026", "17:10", "Stockholm Arlanda", "18:25", "Helsinki"]
            ),
            html_body=None,
            date=datetime(2026, 1, 14, tzinfo=UTC),
            pdf_attachments=[],
        )
        flights = extract_generic_html(msg)
        assert len(flights) == 1
        f = flights[0]
        assert f["flight_number"] == "DY4371"
        assert f["departure_airport"] == "ARN"
        assert f["arrival_airport"] == "HEL"


class TestGuardrails:
    def test_same_dep_arr_rejected(self, seeded_airports_db):
        html = _html("SK533", "ARN", "ARN", "14 Jan 2026", "14:00", "16:00")
        assert extract_generic_html(_msg(html)) == []

    def test_date_too_far_in_future_rejected(self, seeded_airports_db):
        html = _html("SK533", "ARN", "OSL", "14 Jan 2030", "14:00", "16:05")
        assert extract_generic_html(_msg(html)) == []

    def test_old_past_date_allowed(self, seeded_airports_db):
        """Flights from years ago (e.g. 2010) should not be rejected."""
        html = _html("SK533", "ARN", "OSL", "14 Jan 2010", "14:00", "16:05")
        assert len(extract_generic_html(_msg(html))) == 1

    def test_missing_times_returns_empty(self, seeded_airports_db):
        """Without 2 times, no flight can be built."""
        html = _html("SK533", "ARN", "OSL", "14 Jan 2026", "14:00")
        assert extract_generic_html(_msg(html)) == []

    def test_missing_iata_returns_empty(self, seeded_airports_db):
        """Without 2 IATA codes, no flight can be built."""
        html = _html("SK533", "ARN", "14 Jan 2026", "14:00", "16:05")
        assert extract_generic_html(_msg(html)) == []

    def test_no_flight_number_returns_empty(self, seeded_airports_db):
        html = _html("ARN", "OSL", "14 Jan 2026", "14:00", "16:05")
        assert extract_generic_html(_msg(html)) == []

    def test_duplicate_flight_deduplicated(self, seeded_airports_db):
        """Same flight number appearing twice yields only one result."""
        html = _html(
            "SK533",
            "ARN",
            "OSL",
            "14 Jan 2026",
            "14:00",
            "16:05",
            "SK533",
            "ARN",
            "OSL",
            "14 Jan 2026",
            "14:00",
            "16:05",
        )
        flights = extract_generic_html(_msg(html))
        assert len(flights) == 1

    def test_invalid_iata_not_in_db_rejected(self, seeded_airports_db):
        """3-letter tokens that aren't valid airport codes must not be used."""
        html = _html("SK533", "EUR", "DNA", "14 Jan 2026", "14:00", "16:05")
        assert extract_generic_html(_msg(html)) == []
