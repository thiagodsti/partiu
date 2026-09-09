"""
Test: Lufthansa itinerary-table parser (``_extract_itinerary``).

This template ("Your itinerary" / "O seu itinerário") is what booking.lufthansa.com,
booking-lufthansa.com and the shared 15below renderer all emit. Before it was read
directly, these emails were only picked up by the generic line scanner via their
schema.org microdata, which carried a single leg out of six.

Covered here:
  - localised weekday abbreviations ("Thur.", "Fri.", "seg.", "qui.")
  - localised time-unit suffix ("06:45 h" vs "16:20 Hora")
  - non-LH marketing carriers on a Lufthansa booking (LX, plus 4-digit codeshares)
  - per-leg terminals
  - the explicit "+1" next-day arrival marker
  - cancelled legs listed alongside live ones in a schedule-change mail
"""

from datetime import UTC, datetime

import pytest

RULE_LH = type("Rule", (), {"airline_name": "Lufthansa", "airline_code": "LH"})()


def _email(html: str, subject: str = "Booking details"):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="lh-itin-test",
        sender="lufthansa.com <online@booking.lufthansa.com>",
        subject=subject,
        body="",
        date=datetime(2019, 1, 20, tzinfo=UTC),
        html_body=html,
        pdf_attachments=[],
    )


def _html(*lines: str) -> str:
    body = "".join(f"<p>{ln}</p>" for ln in lines)
    return f"<html><body><p>Your itinerary</p>{body}</body></html>"


def _extract(html: str):
    from backend.parsers.airlines.lufthansa import extract

    return extract(_email(html), RULE_LH)


# ---------------------------------------------------------------------------
# English template (booking-lufthansa.com)
# ---------------------------------------------------------------------------

EN_TWO_LEGS = _html(
    "Thur. 24 January 2019",
    ": STOCKHOLM SE - FRANKFURT DE",
    "14:00 h",
    "STOCKHOLM SE ARLANDA (ARN)",
    "TERMINAL 5",
    "16:05 h",
    "FRANKFURT DE FRANKFURT INTL (FRA)",
    "TERMINAL 1",
    "LH803",
    "operated by: LUFTHANSA",
    "Status:",
    "confirmed",
    "Thur. 24 January 2019",
    ": FRANKFURT DE - MILAN IT",
    "21:55 h",
    "FRANKFURT DE FRANKFURT INTL (FRA)",
    "TERMINAL 1",
    "23:05 h",
    "MILAN IT LINATE (LIN)",
    "LH278",
    "operated by: LUFTHANSA",
    "Status:",
    "confirmed",
)


@pytest.fixture(scope="module")
def en_flights(seeded_airports_db):
    return _extract(EN_TWO_LEGS)


class TestEnglishItineraryTable:
    def test_both_legs_extracted(self, en_flights):
        assert len(en_flights) == 2

    def test_flight_numbers(self, en_flights):
        assert [f["flight_number"] for f in en_flights] == ["LH803", "LH278"]

    def test_routes(self, en_flights):
        assert [(f["departure_airport"], f["arrival_airport"]) for f in en_flights] == [
            ("ARN", "FRA"),
            ("FRA", "LIN"),
        ]

    def test_times(self, en_flights):
        assert en_flights[0]["departure_datetime"] == datetime(2019, 1, 24, 14, 0, tzinfo=UTC)
        assert en_flights[0]["arrival_datetime"] == datetime(2019, 1, 24, 16, 5, tzinfo=UTC)

    def test_terminals_captured(self, en_flights):
        assert en_flights[0]["departure_terminal"] == "5"
        assert en_flights[0]["arrival_terminal"] == "1"

    def test_missing_terminal_left_empty(self, en_flights):
        # Linate prints no terminal on this receipt
        assert en_flights[1]["arrival_terminal"] == ""

    def test_thur_weekday_abbreviation_is_read(self, en_flights):
        """Regression: "Thur." is not "Thu." — the old regex required exactly 3 letters."""
        assert en_flights[0]["departure_datetime"].date() == datetime(2019, 1, 24).date()


# ---------------------------------------------------------------------------
# Portuguese template (15below) — codeshare carriers, "+1", cancelled leg
# ---------------------------------------------------------------------------

PT_MIXED_CARRIERS = _html(
    "seg. 20. dezembro 2021:",
    "Estocolmo – Zurique",
    "16:20 Hora",
    "Estocolmo Arlanda (ARN)",
    "Terminal 5",
    "18:45 Hora",
    "Zurique Zurich (ZRH)",
    "LX 4709",
    "operado por:",
    "Swiss International Air Lines",
    "Estatuto:",
    "Cancelada",
    "seg. 20. dezembro 2021:",
    "Zurique – São Paulo",
    "22:45 Hora",
    "Zurique Zurich (ZRH)",
    "06:35 Hora",
    "+1",
    "São Paulo Guarulhos (GRU)",
    "Terminal 3",
    "LX 92",
    "operado por:",
    "Swiss International Air Lines",
    "Estatuto:",
    "confirmado",
    "qui. 20. janeiro 2022:",
    "Frankfurt – Estocolmo",
    "16:05 Hora",
    "Frankfurt Frankfurt (FRA)",
    "Terminal 1",
    "18:10 Hora",
    "Estocolmo Arlanda (ARN)",
    "Terminal 5",
    "LH 806",
    "operado por:",
    "Lufthansa",
    "Estatuto:",
    "confirmado",
)


@pytest.fixture(scope="module")
def pt_flights(seeded_airports_db):
    return _extract(PT_MIXED_CARRIERS)


class TestPortugueseItineraryTable:
    def test_cancelled_leg_is_skipped(self, pt_flights):
        """A schedule-change mail reprints the dropped leg; storing it would
        invent a flight the passenger never takes."""
        assert "LX4709" not in [f["flight_number"] for f in pt_flights]

    def test_remaining_legs_extracted(self, pt_flights):
        assert [f["flight_number"] for f in pt_flights] == ["LX92", "LH806"]

    def test_non_lufthansa_carrier_is_read(self, pt_flights):
        """Regression: the old pattern hard-coded "LH" and dropped every LX leg."""
        assert pt_flights[0]["flight_number"] == "LX92"
        assert (pt_flights[0]["departure_airport"], pt_flights[0]["arrival_airport"]) == (
            "ZRH",
            "GRU",
        )

    def test_localised_weekday_and_day_dot(self, pt_flights):
        assert pt_flights[0]["departure_datetime"].date() == datetime(2021, 12, 20).date()

    def test_next_day_marker_moves_the_arrival_date(self, pt_flights):
        """ "+1" is stated explicitly, so the arrival lands on the 21st."""
        assert pt_flights[0]["arrival_datetime"] == datetime(2021, 12, 21, 6, 35, tzinfo=UTC)

    def test_hora_time_suffix(self, pt_flights):
        assert pt_flights[0]["departure_datetime"] == datetime(2021, 12, 20, 22, 45, tzinfo=UTC)

    def test_later_journey_year_rolls_over(self, pt_flights):
        assert pt_flights[1]["departure_datetime"].year == 2022


class TestItineraryGuardrails:
    def test_zero_width_spaces_in_times_survive(self, seeded_airports_db):
        """Lufthansa peppers this template with zero-width spaces ("1<zwsp>4:0<zwsp>0 h")."""
        html = _html(
            "Fri. 29 March 2024:",
            "Stockholm – Frankfurt",
            "0​6:4​5\xa0h",
            "Stockholm Arlanda\xa0(ARN)",
            "0​9:0​0\xa0h",
            "Frankfurt Frankfurt\xa0(FRA)",
            "LH 809",
        )
        flights = _extract(html)
        assert len(flights) == 1
        assert flights[0]["departure_datetime"] == datetime(2024, 3, 29, 6, 45, tzinfo=UTC)

    def test_block_without_a_flight_number_yields_nothing(self, seeded_airports_db):
        html = _html(
            "Fri. 29 March 2024:",
            "06:45 h",
            "Stockholm Arlanda (ARN)",
            "09:00 h",
            "Frankfurt Frankfurt (FRA)",
        )
        assert _extract(html) == []

    def test_block_with_one_airport_yields_nothing(self, seeded_airports_db):
        html = _html(
            "Fri. 29 March 2024:",
            "06:45 h",
            "Stockholm Arlanda (ARN)",
            "09:00 h",
            "LH 809",
        )
        assert _extract(html) == []

    def test_unknown_iata_is_rejected(self, seeded_airports_db):
        html = _html(
            "Fri. 29 March 2024:",
            "06:45 h",
            "Nowhere Special (ZZZ)",
            "09:00 h",
            "Elsewhere (QQQ)",
            "LH 809",
        )
        assert _extract(html) == []

    def test_overnight_without_marker_is_still_fixed(self, seeded_airports_db):
        """No "+1" in the email — the clock wrap is the only signal left."""
        html = _html(
            "Fri. 29 March 2024:",
            "22:30 h",
            "Stockholm Arlanda (ARN)",
            "01:15 h",
            "Frankfurt Frankfurt (FRA)",
            "LH 809",
        )
        flights = _extract(html)
        assert len(flights) == 1
        assert flights[0]["arrival_datetime"] > flights[0]["departure_datetime"]
        assert flights[0]["arrival_datetime"].day == 30
