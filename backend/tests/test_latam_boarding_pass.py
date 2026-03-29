"""
Test: LATAM boarding-pass seat-update extractor.

Fixtures cover two check-in confirmation emails that contain seat assignments
for flights already in the DB — the extractor should return seat data, not
create new flights.

  latam_boarding_pass_sp_anonymized.json   → LA3357, dep 2026-03-16, seat 18F
  latam_boarding_pass_milan_anonymized.json → LA8072, dep 2026-03-16, seat 14L
"""

import pytest
from conftest import load_anonymized_fixture


@pytest.fixture(scope="module")
def sp_email():
    return load_anonymized_fixture("latam_boarding_pass_sp_anonymized.json")


@pytest.fixture(scope="module")
def milan_email():
    return load_anonymized_fixture("latam_boarding_pass_milan_anonymized.json")


class TestSPBoardingPass:
    def test_detects_boarding_pass(self, sp_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(sp_email)
        assert result is not None

    def test_flight_number(self, sp_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(sp_email)
        assert result is not None
        assert result["flight_number"] == "LA3357"

    def test_departure_date(self, sp_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(sp_email)
        assert result is not None
        assert result["dep_date"] == "2026-03-16"

    def test_seat(self, sp_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(sp_email)
        assert result is not None
        assert result["seat"] == "18F"


class TestMilanBoardingPass:
    def test_detects_boarding_pass(self, milan_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(milan_email)
        assert result is not None

    def test_flight_number(self, milan_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(milan_email)
        assert result is not None
        assert result["flight_number"] == "LA8072"

    def test_departure_date(self, milan_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(milan_email)
        assert result is not None
        assert result["dep_date"] == "2026-03-16"

    def test_seat(self, milan_email):
        from backend.parsers.airlines.latam import extract_seat_update

        result = extract_seat_update(milan_email)
        assert result is not None
        assert result["seat"] == "14L"


class TestNonBoardingPassEmails:
    def test_checkin_reminder_returns_none(self):
        """Check-in reminder has no seat yet — should not extract."""
        from datetime import UTC, datetime

        from backend.parsers.airlines.latam import extract_seat_update
        from backend.parsers.email_connector import EmailMessage

        # Body with flight + date but no "Check-in feito" / seat line
        reminder = EmailMessage(
            message_id="test-reminder",
            sender="no-reply@info.latam.com",
            subject="É hora de fazer seu Check-in!",
            body="É hora de fazer seu Check-in!\nLA8072\n16/03/26",
            date=datetime.now(tz=UTC),
            html_body="",
            pdf_attachments=[],
        )
        assert extract_seat_update(reminder) is None
