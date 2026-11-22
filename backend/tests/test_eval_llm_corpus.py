"""Tests for backend.tools.eval_llm_corpus (scoring only; Ollama is never called)."""

from datetime import UTC, datetime
from unittest.mock import patch


def _row(kind, truth, got):
    return {
        "kind": kind,
        "rule": "AD",
        "subject": "s",
        "truth": sorted(truth),
        "got": sorted(got),
        "exact": len(set(truth) & set(got)),
        "route_only": 0,
        "wrong": 0,
        "error": "",
        "elapsed": 1.0,
    }


class TestRender:
    def test_an_extra_leg_on_another_date_is_not_fully_right(self):
        from backend.tools.eval_llm_corpus import render

        leg = ("AD4849", "VCP", "FLN", "2026-03-02")
        extra = ("AD4849", "VCP", "FLN", "2026-03-03")
        out = render("m", [_row("pos", [leg], [leg, extra])])
        assert "mails all right  0/1" in out
        assert "[pos AD]" in out

    def test_an_exact_mail_is_fully_right(self):
        from backend.tools.eval_llm_corpus import render

        leg = ("AD4849", "VCP", "FLN", "2026-03-02")
        out = render("m", [_row("pos", [leg], [leg])])
        assert "mails all right  1/1" in out


class TestLocalDate:
    def test_utc_date_becomes_the_departure_airports_date(self):
        from backend.tools.eval_llm_corpus import _local_date

        # 22:30 UTC is 01:30 the next day in Doha (UTC+3)
        with patch("backend.airports.timezone._get_airport_timezone", return_value="Asia/Qatar"):
            assert _local_date("2021-12-14 22:30", "DOH") == "2021-12-15"

    def test_unknown_airport_keeps_the_utc_date(self):
        from backend.tools.eval_llm_corpus import _local_date

        with patch("backend.airports.timezone._get_airport_timezone", return_value=None):
            assert _local_date("2021-12-14 22:30", "XXX") == "2021-12-14"


class TestScoreFollowsTheSyncPath:
    def test_legs_are_validated_together_so_a_january_leg_rolls_over(self, test_db):
        """Production validates a mail's legs as one itinerary, which moves a
        year-less January return after a December departure into next year."""
        import json
        from unittest.mock import patch

        from backend.integrations.llm import parser as llm
        from backend.parsers.email_connector import EmailMessage
        from backend.tools.eval_llm_corpus import score

        answer = json.dumps(
            {
                "has_flight": True,
                "booking_reference": "TESTR5",
                "flights": [
                    {
                        "flight_number": "XY1",
                        "dep_airport": "ARN",
                        "arr_airport": "LIS",
                        "dep_datetime": "2026-12-22T10:00:00",
                        "arr_datetime": "2026-12-22T14:00:00",
                        "dep_date": "2026-12-22",
                        "airline_code": "XY",
                    },
                    {
                        "flight_number": "XY2",
                        "dep_airport": "LIS",
                        "arr_airport": "ARN",
                        "dep_datetime": "2026-01-15T10:00:00",
                        "arr_datetime": "2026-01-15T14:00:00",
                        "dep_date": "2026-01-15",
                        "airline_code": "XY",
                    },
                ],
            }
        )
        email = EmailMessage(
            message_id="<t@x>",
            sender="no-reply@airline.example",
            subject="Booking TESTR5",
            body="XY 1 ARN LIS 22 Dec 10:00, XY 2 LIS ARN 15 Jan 10:00",
            date=datetime(2026, 11, 1, tzinfo=UTC),
        )
        row = {
            "kind": "pos",
            "rule": "XY",
            "subject": "Booking TESTR5",
            "legs": [
                ("XY1", "ARN", "LIS", "2026-12-22 10:00"),
                ("XY2", "LIS", "ARN", "2027-01-15 10:00"),
            ],
        }
        with patch.object(llm, "_call_ollama", return_value=answer):
            result = score(email, row, "m", "u", 1)
        assert ("XY2", "LIS", "ARN", "2027-01-15") in result["got"]
        assert result["exact"] == 2
