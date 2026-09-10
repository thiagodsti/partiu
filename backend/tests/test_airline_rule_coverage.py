"""
Tests for the airline-rule formats that replaced the generic line scanners.

Each class below covers one email template that used to reach no rule at all (or
whose rule returned nothing) and was therefore picked up — wrongly or partially —
by the generic HTML/PDF scanners. The scanners are gone, so these are the tests
that keep those emails parsing.
"""

from datetime import UTC, datetime

import pytest


def _rule(name: str, code: str):
    return type("Rule", (), {"airline_name": name, "airline_code": code})()


def _email(
    *,
    sender: str = "test@example.com",
    subject: str = "",
    html: str = "",
    body: str = "",
    date: datetime | None = None,
):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="rule-coverage-test",
        sender=sender,
        subject=subject,
        body=body,
        date=date or datetime(2024, 1, 1, tzinfo=UTC),
        html_body=html,
        pdf_attachments=[],
    )


def _html(*lines: str) -> str:
    return "<html><body>" + "".join(f"<p>{ln}</p>" for ln in lines) + "</body></html>"


def _routes(flights):
    return [(f["flight_number"], f["departure_airport"], f["arrival_airport"]) for f in flights]


# ---------------------------------------------------------------------------
# LATAM — city-name itinerary (no IATA code anywhere on the page)
# ---------------------------------------------------------------------------


class TestLatamCityNameItinerary:
    """LATAM's purchase-confirmation and flight-info mails print city names only.
    Every other LATAM format anchors on "(GRU)"-style codes, so these fell through
    to the generic scanner, which only ever recovered the first leg of a round trip.
    """

    ROUND_TRIP = _html(
        "Itinerário da viagem",
        "Voo de ida",
        "24 de dez. de 2024",
        "8:00",
        "São Paulo",
        "LA3300",
        "24 de dez. de 2024",
        "9:15",
        "Florianópolis",
        "Voo de volta",
        "24 de jan. de 2025",
        "11:45",
        "Florianópolis",
        "LA3357",
        "24 de jan. de 2025",
        "13:10",
        "São Paulo",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.latam import extract

        return extract(_email(html=self.ROUND_TRIP), _rule("LATAM Airlines", "LA"))

    def test_both_directions_extracted(self, flights):
        """Regression: the generic scanner returned only the outbound leg."""
        assert len(flights) == 2

    def test_routes_resolved_from_city_names(self, flights):
        assert _routes(flights) == [
            ("LA3300", "GRU", "FLN"),
            ("LA3357", "FLN", "GRU"),
        ]

    def test_departure_time(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2024, 12, 24, 8, 0, tzinfo=UTC)

    def test_return_leg_year(self, flights):
        assert flights[1]["departure_datetime"].year == 2025

    def test_parenthesised_flight_number_variant(self, seeded_airports_db):
        """The "Informação de voo" mail wraps the flight number in parentheses."""
        from backend.parsers.airlines.latam import extract

        html = _html(
            "Informação de voo",
            "23 de fev de 2024",
            "10:25",
            "Florianópolis",
            "(LA3301)",
            "23 de fev de 2024",
            "11:45",
            "São Paulo",
        )
        flights = extract(_email(html=html), _rule("LATAM Airlines", "LA"))
        assert _routes(flights) == [("LA3301", "FLN", "GRU")]

    def test_label_lines_are_not_read_as_cities(self, seeded_airports_db):
        from backend.parsers.airlines.latam import extract

        html = _html(
            "Itinerário da viagem",
            "24 de dez. de 2024",
            "8:00",
            "Tarifa Standard",
            "LA3300",
            "24 de dez. de 2024",
            "9:15",
            "Total",
        )
        assert extract(_email(html=html), _rule("LATAM Airlines", "LA")) == []


# ---------------------------------------------------------------------------
# TAP — reservation change (full weekday/month) and the "Flight details" card
# ---------------------------------------------------------------------------


class TestTapReservationChange:
    """Same template as the booking confirmation, but with the weekday and month
    spelled out and a year appended: "Friday, 10 November 2023"."""

    HTML = _html(
        "Booking Reference",
        "TESTR9",
        "Your itinerary",
        "Friday, 10 November 2023",
        "19:30",
        "ARN",
        "23:00",
        "LIS",
        "TP783",
        "TP783 - STOCKHOLM (Terminal 5) to",
        "LISBON",
        "Saturday, 18 November 2023",
        "08:05",
        "LIS",
        "13:30",
        "ARN",
        "TP780",
        "TP780 - LISBON (Terminal 1) to",
        "STOCKHOLM",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.tap import extract

        return extract(
            _email(
                html=self.HTML, subject="Reservation Change", date=datetime(2023, 9, 27, tzinfo=UTC)
            ),
            _rule("TAP Air Portugal", "TP"),
        )

    def test_both_legs_extracted(self, flights):
        assert _routes(flights) == [
            ("TP783", "ARN", "LIS"),
            ("TP780", "LIS", "ARN"),
        ]

    def test_full_month_name_with_year_is_read(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2023, 11, 10, 19, 30, tzinfo=UTC)

    def test_second_leg_date(self, flights):
        assert flights[1]["departure_datetime"] == datetime(2023, 11, 18, 8, 5, tzinfo=UTC)

    def test_abbreviated_form_still_works(self, seeded_airports_db):
        """The original "Fri, 10 Nov" (no year) rendering must keep parsing."""
        from backend.parsers.airlines.tap import extract

        html = _html(
            "Fri, 10 Nov",
            "19:05",
            "ARN",
            "22:35",
            "LIS",
            "Direct",
            "TP 783",
        )
        flights = extract(
            _email(html=html, date=datetime(2023, 9, 1, tzinfo=UTC)),
            _rule("TAP Air Portugal", "TP"),
        )
        assert _routes(flights) == [("TP783", "ARN", "LIS")]


class TestTapCheckinCard:
    """The older check-in mail stacks code / city / date / time per endpoint."""

    HTML = _html(
        "Check-in open",
        "Booking reference:",
        "PH3KFM",
        "Flight details",
        "TP 788",
        "LIS",
        "Lisboa",
        "5 Dec 18",
        "12:45",
        "ARN",
        "Estocolmo /",
        "5 Dec 18",
        "18:10",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.tap import extract

        return extract(
            _email(html=self.HTML, subject="Check-in here", date=datetime(2018, 12, 4, tzinfo=UTC)),
            _rule("TAP Air Portugal", "TP"),
        )

    def test_flight_extracted(self, flights):
        assert _routes(flights) == [("TP788", "LIS", "ARN")]

    def test_two_digit_year_resolved(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2018, 12, 5, 12, 45, tzinfo=UTC)

    def test_arrival_time(self, flights):
        assert flights[0]["arrival_datetime"] == datetime(2018, 12, 5, 18, 10, tzinfo=UTC)

    def test_booking_reference(self, flights):
        assert flights[0]["booking_reference"] == "PH3KFM"


# ---------------------------------------------------------------------------
# Finnair — booking confirmation, and the cancellation notice that must not parse
# ---------------------------------------------------------------------------


def _finnair_html(heading_blocks: list[tuple[str, str, str, str, str, str, str]], *, prefix=()):
    lines = list(prefix)
    for heading, date, dep_t, dep, arr_t, arr, fn in heading_blocks:
        lines += [
            heading,
            date,
            "Total längd 1 h 0 min",
            dep_t,
            dep,
            arr_t,
            arr,
            "(Terminal 2)",
            fn,
            "Trafikeras av Finnair",
        ]
    return _html(*lines)


class TestFinnairBookingConfirmation:
    HTML = _finnair_html(
        [
            ("Utresa", "2024-07-29", "07:15", "ARN", "09:15", "HEL", "AY806"),
            ("Hemresa", "2024-07-31", "15:55", "HEL", "15:55", "ARN", "AY813"),
        ],
        prefix=("Tack för att du bokar med Finnair", "Bokningsnummer", "TWJRQF"),
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.finnair import extract

        return extract(
            _email(html=self.HTML, subject="Bokningsbekräftelse och information för TWJRQF"),
            _rule("Finnair", "AY"),
        )

    def test_both_directions_extracted(self, flights):
        assert _routes(flights) == [
            ("AY806", "ARN", "HEL"),
            ("AY813", "HEL", "ARN"),
        ]

    def test_iso_date_per_journey(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2024, 7, 29, 7, 15, tzinfo=UTC)
        assert flights[1]["departure_datetime"] == datetime(2024, 7, 31, 15, 55, tzinfo=UTC)

    def test_equal_local_times_are_kept(self, flights):
        """HEL→ARN departs and lands at 15:55 local — the hour is eaten by the
        timezone change, so this is not an overnight to be "fixed"."""
        assert flights[1]["arrival_datetime"] == datetime(2024, 7, 31, 15, 55, tzinfo=UTC)


class TestFinnairCancellationNotice:
    """The cancellation mail reprints the full itinerary of flights that are no
    longer happening, in exactly the confirmation layout."""

    HTML = _finnair_html(
        [("Utresa", "2024-07-29", "07:15", "ARN", "09:15", "HEL", "AY806")],
        prefix=("Din bokning har avbokats", "Cancelled booking reference:", "TWJRQF"),
    )

    def test_no_flights_extracted(self, seeded_airports_db):
        from backend.parsers.airlines.finnair import extract

        assert (
            extract(
                _email(html=self.HTML, subject="Bekräftelse på din avbokning"),
                _rule("Finnair", "AY"),
            )
            == []
        )

    def test_connecting_journey_is_declined(self, seeded_airports_db):
        """Two flight numbers under one heading means the times shown span the
        whole journey, not either leg."""
        from backend.parsers.airlines.finnair import extract

        html = _html(
            "Utresa",
            "2024-07-29",
            "07:15",
            "ARN",
            "14:30",
            "LIS",
            "AY806",
            "AY1234",
        )
        assert extract(_email(html=html), _rule("Finnair", "AY")) == []


# ---------------------------------------------------------------------------
# Austrian — "Travel details" check-in card
# ---------------------------------------------------------------------------


class TestAustrianTravelDetailsCard:
    HTML = _html(
        "Booking Code:",
        "RHFNEJ",
        "Travel details",
        "03.04.2024",
        "OS317",
        "VIE",
        "ARN",
        "Vienna",
        "Stockholm",
        "20:25",
        "22:35",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.austrian import extract

        return extract(
            _email(
                html=self.HTML,
                subject="Your flight is ready for check-in | From Vienna to Stockholm",
                date=datetime(2024, 4, 2, tzinfo=UTC),
            ),
            _rule("Austrian Airlines", "OS"),
        )

    def test_flight_extracted(self, flights):
        assert _routes(flights) == [("OS317", "VIE", "ARN")]

    def test_dotted_date_and_times(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2024, 4, 3, 20, 25, tzinfo=UTC)
        assert flights[0]["arrival_datetime"] == datetime(2024, 4, 3, 22, 35, tzinfo=UTC)

    def test_booking_reference(self, flights):
        assert flights[0]["booking_reference"] == "RHFNEJ"


# ---------------------------------------------------------------------------
# Norwegian — localised travel-documents heading and year-first dates
# ---------------------------------------------------------------------------


class TestNorwegianSwedishTravelDocuments:
    BODY = "\n".join(
        [
            "Bokningsbekräftelse",
            "DIN BOKNINGSREFERENS ÄR:",
            "QAJV6E",
            "Flyginformation",
            "DY4371",
            "-",
            "2019 aug 14",
            "",
            "17:10",
            "Stockholm-Arlanda",
            "",
            "20:45",
            "Catania",
            "",
            "LowFare",
            "DY4372",
            "-",
            "2019 aug 24",
            "",
            "14:45",
            "Catania",
            "",
            "18:25",
            "Stockholm-Arlanda",
            "",
            "LowFare",
        ]
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.norwegian import extract

        return extract(
            _email(
                sender='"Norwegian.se" <noreply@norwegian.se>',
                subject="Resehandlingar Ref. QAJV6E",
                body=self.BODY,
                date=datetime(2019, 5, 21, tzinfo=UTC),
            ),
            _rule("Norwegian Air Shuttle", "DY"),
        )

    def test_both_legs_extracted(self, flights):
        """Regression: the generic scanner produced both legs pointing at CTA."""
        assert _routes(flights) == [
            ("DY4371", "ARN", "CTA"),
            ("DY4372", "CTA", "ARN"),
        ]

    def test_year_first_date_is_read(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2019, 8, 14, 17, 10, tzinfo=UTC)

    def test_return_leg_date(self, flights):
        assert flights[1]["departure_datetime"] == datetime(2019, 8, 24, 14, 45, tzinfo=UTC)

    def test_swedish_heading_matched(self, flights):
        """Regression: only "YOUR BOOKING REFERENCE IS" was recognised before."""
        assert flights


# ---------------------------------------------------------------------------
# Vueling — new airline rule
# ---------------------------------------------------------------------------


class TestVuelingBookingConfirmation:
    HTML = _html(
        "Booking code",
        "TGERVW",
        "Outbound",
        "Basic",
        "Wednesday, 27 April 2022",
        "Stockholm (T2)",
        "Barcelona (T1)",
        "ARN",
        "BCN",
        "11:35h",
        "15:20h",
        "VY1266",
        "Return",
        "Basic",
        "Sunday, 01 May 2022",
        "Barcelona (T1)",
        "Stockholm (T2)",
        "BCN",
        "ARN",
        "15:25h",
        "19:10h",
        "VY1265",
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.airlines.vueling import extract

        return extract(
            _email(html=self.HTML, subject="Your booking confirmation - TGERVW ARN-BCN 27 April"),
            _rule("Vueling", "VY"),
        )

    def test_both_directions_extracted(self, flights):
        assert _routes(flights) == [
            ("VY1266", "ARN", "BCN"),
            ("VY1265", "BCN", "ARN"),
        ]

    def test_h_suffixed_times(self, flights):
        assert flights[0]["departure_datetime"] == datetime(2022, 4, 27, 11, 35, tzinfo=UTC)
        assert flights[0]["arrival_datetime"] == datetime(2022, 4, 27, 15, 20, tzinfo=UTC)

    def test_codes_not_paired_with_the_wrong_city(self, flights):
        """Both city lines precede both IATA lines; reading the block pairwise
        from the top would mate Stockholm with Barcelona's terminal."""
        assert flights[1]["departure_airport"] == "BCN"

    def test_return_date(self, flights):
        assert flights[1]["departure_datetime"].date() == datetime(2022, 5, 1).date()

    def test_rule_is_registered(self):
        from backend.parsers.builtin_rules import get_builtin_rules

        vy = [r for r in get_builtin_rules() if r.airline_code == "VY"]
        assert len(vy) == 1
        assert vy[0].extractor is not None

    def test_rule_matches_the_sender(self):
        import re

        from backend.parsers.builtin_rules import get_builtin_rules

        vy = next(r for r in get_builtin_rules() if r.airline_code == "VY")
        assert re.search(
            vy.sender_pattern, "Vueling Airlines <no-reply@vueling.com>", re.IGNORECASE
        )
