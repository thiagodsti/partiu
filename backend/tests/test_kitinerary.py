"""parsers/kitinerary.py: KDE Itinerary's extractor as an extraction tier.

The real binary is x86_64-only and lives in the Docker image, so these tests
stand a small script in for it: it records what it was given and prints the
JSON-LD the real extractor prints (times as QDateTime objects, as measured).
"""

import json
import sys
import textwrap
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from backend.parsers import kitinerary

_LEG = {
    "@context": "http://schema.org",
    "@type": "FlightReservation",
    "reservationNumber": "TEST42",
    "reservationStatus": "http://schema.org/ReservationConfirmed",
    "reservationFor": {
        "@type": "Flight",
        "airline": {"@type": "Airline", "iataCode": "U2", "name": "easyJet"},
        "flightNumber": "8205",
        "departureAirport": {"@type": "Airport", "iataCode": "STN", "name": "London Stansted"},
        "departureTime": {
            "@type": "QDateTime",
            "@value": "2026-03-10T07:05:00+00:00",
            "timezone": "Europe/London",
        },
        "arrivalAirport": {"@type": "Airport", "iataCode": "LIS", "name": "Lisbon"},
        "arrivalTime": {
            "@type": "QDateTime",
            "@value": "2026-03-10T09:50:00+00:00",
            "timezone": "Europe/Lisbon",
        },
    },
}


def _fake_extractor(tmp_path, output, exit_code=0):
    """A stand-in for kitinerary-extractor that logs its argv and stdin."""
    log = tmp_path / "calls.json"
    script = tmp_path / "kitinerary-extractor"
    script.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            f"""
            import json, sys
            data = sys.stdin.buffer.read()
            with open({str(log)!r}, "w") as f:
                json.dump({{"argv": sys.argv[1:], "stdin": data.decode("utf-8", "replace")}}, f)
            sys.stdout.write({output!r})
            sys.exit({exit_code})
            """
        )
    )
    script.chmod(0o755)
    return script, log


def _email(raw=None, **kw):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="<kit@test>",
        sender=kw.get("sender", "easyJet <noreply@easyjet.com>"),
        subject=kw.get("subject", "Your booking EZY123"),
        body=kw.get("body", "U2 8205 London Stansted (STN) 07:05 → Lisbon (LIS) 09:50"),
        date=datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
        html_body=kw.get("html_body", "<p>html body</p>"),
        pdf_attachments=[],
        raw_eml=raw,
    )


@pytest.fixture
def use(tmp_path):
    def _use(output, exit_code=0):
        script, log = _fake_extractor(tmp_path, output, exit_code)
        patcher = patch.object(kitinerary.settings, "KITINERARY_EXTRACTOR", str(script))
        patcher.start()
        return log, patcher

    patchers = []

    def wrapped(output, exit_code=0):
        log, p = _use(output, exit_code)
        patchers.append(p)
        return log

    yield wrapped
    for p in patchers:
        p.stop()


class TestAvailability:
    def test_off_when_emptied(self):
        with patch.object(kitinerary.settings, "KITINERARY_EXTRACTOR", ""):
            assert not kitinerary.available()
            assert kitinerary.extract_kitinerary_flights(_email()) == []

    def test_off_when_the_binary_is_missing(self, tmp_path):
        with patch.object(kitinerary.settings, "KITINERARY_EXTRACTOR", str(tmp_path / "nope")):
            assert not kitinerary.available()
            assert kitinerary.extract_kitinerary_flights(_email()) == []

    def test_off_when_not_executable(self, tmp_path):
        f = tmp_path / "kitinerary-extractor"
        f.write_text("not a program")
        f.chmod(0o644)
        with patch.object(kitinerary.settings, "KITINERARY_EXTRACTOR", str(f)):
            assert not kitinerary.available()


class TestExtraction:
    def test_a_flight_reservation_becomes_a_utc_leg(self, use, seeded_airports_db):
        use(json.dumps([_LEG]))

        (leg,) = kitinerary.extract_kitinerary_flights(_email())

        assert leg["flight_number"] == "U28205"
        assert (leg["departure_airport"], leg["arrival_airport"]) == ("STN", "LIS")
        assert leg["departure_datetime"] == datetime(2026, 3, 10, 7, 5, tzinfo=UTC)
        assert leg["arrival_datetime"] == datetime(2026, 3, 10, 9, 50, tzinfo=UTC)
        assert leg["booking_reference"] == "TEST42"
        assert leg["_times_already_utc"] is True

    def test_the_same_refusals_as_the_markup_reader(self, use, seeded_airports_db):
        no_time = json.loads(json.dumps(_LEG))
        no_time["reservationFor"]["departureTime"] = "2026-03-10"
        no_code = json.loads(json.dumps(_LEG))
        no_code["reservationFor"]["arrivalAirport"] = {"@type": "Airport", "name": "Milan"}
        cancelled = json.loads(json.dumps(_LEG))
        cancelled["reservationStatus"] = "http://schema.org/ReservationCancelled"
        use(json.dumps([no_time, no_code, cancelled]))

        assert kitinerary.extract_kitinerary_flights(_email()) == []

    def test_an_airport_the_email_does_not_name_is_refused(self, use, seeded_airports_db):
        # KItinerary fills a missing IATA code from the airport's name; Partiu
        # keeps an airport only when the email itself names it.
        use(json.dumps([_LEG]))
        email = _email(body="U2 8205 London Stansted (STN) 07:05, arriving 09:50")
        assert kitinerary.extract_kitinerary_flights(email) == []

    def test_an_airport_named_by_its_city_is_kept(self, use, seeded_airports_db):
        use(json.dumps([_LEG]))
        email = _email(body="U2 8205 departs STN 07:05 and lands in Lisbon at 09:50")
        assert len(kitinerary.extract_kitinerary_flights(email)) == 1

    def test_non_flight_results_are_ignored(self, use):
        use(json.dumps([{"@type": "LodgingReservation", "reservationFor": {"name": "Hotel"}}]))
        assert kitinerary.extract_kitinerary_flights(_email()) == []

    def test_the_original_bytes_go_to_stdin_with_the_context_date(self, use):
        log = use("[]")
        kitinerary.run_extractor(_email(raw=b"From: a@b\r\nSubject: original\r\n\r\nraw!"))

        call = json.loads(log.read_text())
        assert "raw!" in call["stdin"]
        assert call["argv"][:2] == ["--context-date", "2026-01-05T12:00:00+00:00"]

    def test_without_raw_bytes_the_email_is_rebuilt(self, use):
        log = use("[]")
        kitinerary.run_extractor(_email(raw=None, html_body="<p>rebuilt html</p>"))

        stdin = json.loads(log.read_text())["stdin"]
        assert "Subject: Your booking EZY123" in stdin
        assert "rebuilt html" in stdin


class TestFailuresAreNeverFatal:
    def test_non_zero_exit(self, use):
        use(json.dumps([_LEG]), exit_code=1)
        assert kitinerary.extract_kitinerary_flights(_email()) == []

    def test_unparseable_output(self, use):
        use("this is not json")
        assert kitinerary.extract_kitinerary_flights(_email()) == []

    def test_timeout(self, use):
        import subprocess

        use("[]")
        with patch.object(
            kitinerary.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 30)
        ):
            assert kitinerary.extract_kitinerary_flights(_email()) == []
