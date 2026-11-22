"""Tests for the schema.org flight reader (extract_flight_reservations).

Synthetic markup, for the reason given in test_schema_org_parser.py: every shape
below copies a real airline email's *structure* (Ryanair, Lufthansa, TAP,
Austrian) with invented names, references and seats.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from backend.parsers.schema_org import extract_flight_reservations


class _Email:
    def __init__(self, html_body="", body="", sender="noreply@airline.example", subject="Trip"):
        self.html_body = html_body
        self.body = body
        self.sender = sender
        self.subject = subject


def _leg(
    number="2878",
    airline="FR",
    dep='<meta itemprop="name" content="Milan (Bergamo)"><meta itemprop="iataCode" content="BGY">',
    arr='<meta itemprop="name" content="Stockholm Arlanda"><meta itemprop="iataCode" content="ARN">',
    dep_time="2026-04-23T17:55:00+02:00",
    arr_time="2026-04-23T20:35:00+02:00",
    status="http://schema.org/Confirmed",
    passenger="Alex Example",
    ref="TESTR5",
) -> str:
    dep_time_tag = f'<meta itemprop="departureTime" content="{dep_time}">' if dep_time else ""
    arr_time_tag = f'<meta itemprop="arrivalTime" content="{arr_time}">' if arr_time else ""
    return f"""
<div itemscope itemtype="http://schema.org/FlightReservation">
  <meta itemprop="reservationNumber" content="{ref}">
  <link itemprop="reservationStatus" href="{status}">
  <div itemprop="underName" itemscope itemtype="http://schema.org/Person">
    <meta itemprop="name" content="{passenger}">
  </div>
  <div itemprop="reservationFor" itemscope itemtype="http://schema.org/Flight">
    <meta itemprop="flightNumber" content="{number}">
    <div itemprop="airline" itemscope itemtype="http://schema.org/Airline">
      <meta itemprop="name" content="Example Air"><meta itemprop="iataCode" content="{airline}">
    </div>
    <div itemprop="departureAirport" itemscope itemtype="http://schema.org/Airport">{dep}</div>
    {dep_time_tag}
    <div itemprop="arrivalAirport" itemscope itemtype="http://schema.org/Airport">{arr}</div>
    {arr_time_tag}
  </div>
  <meta itemprop="airplaneSeat" content="12C">
</div>"""


def _mail(*legs: str) -> _Email:
    return _Email("<html><body>" + "".join(legs) + "</body></html>")


class TestReadsALeg:
    def test_microdata_leg(self):
        (f,) = extract_flight_reservations(_mail(_leg()))
        assert f["flight_number"] == "FR2878"
        assert (f["departure_airport"], f["arrival_airport"]) == ("BGY", "ARN")
        assert f["booking_reference"] == "TESTR5"
        assert f["passenger_name"] == "Alex Example"
        assert f["seat"] == "12C"
        assert f["airline_code"] == "FR"

    def test_prefixed_flight_number_is_kept(self):
        (f,) = extract_flight_reservations(_mail(_leg(number="LH 809", airline="LH")))
        assert f["flight_number"] == "LH809"

    def test_json_ld_leg(self):
        payload = """{"@type": "FlightReservation", "reservationNumber": "TESTR5",
          "reservationFor": {"@type": "Flight", "flightNumber": "117",
            "airline": {"@type": "Airline", "iataCode": "SK"},
            "departureAirport": {"@type": "Airport", "iataCode": "ARN"},
            "departureTime": "2026-06-10T06:15:00+02:00",
            "arrivalAirport": {"@type": "Airport", "iataCode": "CPH"}}}"""
        html = f'<script type="application/ld+json">{payload}</script>'
        (f,) = extract_flight_reservations(_Email(html))
        assert (f["flight_number"], f["departure_airport"], f["arrival_airport"]) == (
            "SK117",
            "ARN",
            "CPH",
        )
        assert f["arrival_datetime"] is None


class TestTimes:
    def test_offset_is_honoured(self):
        """Airline offsets were right in every measured mail, unlike Airbnb's."""
        (f,) = extract_flight_reservations(_mail(_leg(dep_time="2026-01-24T14:00:00+01:00")))
        assert f["departure_datetime"] == datetime(2026, 1, 24, 13, 0, tzinfo=UTC)

    def test_basic_iso_format_with_z(self):
        """Lufthansa writes 20240329T054500Z, and the Z is true UTC."""
        (f,) = extract_flight_reservations(_mail(_leg(dep_time="20260329T054500Z")))
        assert f["departure_datetime"] == datetime(2026, 3, 29, 5, 45, tzinfo=UTC)

    def test_naive_time_is_local_to_its_airport(self):
        utc = datetime(2026, 1, 24, 13, 0, tzinfo=UTC)
        with patch("backend.airports.timezone.localize_to_utc", return_value=utc) as localize:
            (f,) = extract_flight_reservations(
                _mail(_leg(dep_time="2026-01-24T14:00:00", arr_time=None))
            )
        localize.assert_called_once_with(datetime(2026, 1, 24, 14, 0), "BGY")
        assert f["departure_datetime"] == utc

    def test_leg_is_flagged_as_utc_for_the_pipeline(self):
        (f,) = extract_flight_reservations(_mail(_leg()))
        assert f["_times_already_utc"] is True

    @pytest.mark.parametrize("value", ["2026-01-24", "23FEB", ""])
    def test_no_clock_time_means_no_leg(self, value):
        """A check-in mail's bare date and TAP's "23FEB" say nothing about when."""
        assert extract_flight_reservations(_mail(_leg(dep_time=value))) == []


class TestRefusesToGuess:
    def test_airport_named_but_not_coded_is_dropped(self):
        """Ryanair marks a Bergamo arrival as just "Milan", which resolves to
        Malpensa: a missing leg is visible, a wrong airport is not."""
        arr = '<meta itemprop="name" content="Milan">'
        assert extract_flight_reservations(_mail(_leg(arr=arr))) == []

    def test_code_written_as_the_name_is_read(self):
        arr = '<meta itemprop="name" content="ARN">'
        (f,) = extract_flight_reservations(_mail(_leg(arr=arr)))
        assert f["arrival_airport"] == "ARN"

    def test_same_airport_both_ends_is_dropped(self):
        same = '<meta itemprop="iataCode" content="ARN">'
        assert extract_flight_reservations(_mail(_leg(dep=same, arr=same))) == []

    def test_digits_without_an_airline_code_are_dropped(self):
        assert extract_flight_reservations(_mail(_leg(airline=""))) == []

    def test_cancelled_reservation_is_skipped(self):
        status = "http://schema.org/ReservationCancelled"
        assert extract_flight_reservations(_mail(_leg(status=status))) == []


class TestDeduplication:
    def test_leg_restated_per_passenger_comes_once(self):
        legs = extract_flight_reservations(
            _mail(_leg(passenger="Alex Example"), _leg(passenger="Sam Example"))
        )
        assert len(legs) == 1

    def test_round_trip_gives_two_legs(self):
        back = _leg(
            number="2879",
            dep='<meta itemprop="iataCode" content="ARN">',
            arr='<meta itemprop="iataCode" content="BGY">',
            dep_time="2026-04-30T06:10:00+02:00",
            arr_time="2026-04-30T08:50:00+02:00",
        )
        legs = extract_flight_reservations(_mail(_leg(), back))
        assert [f["flight_number"] for f in legs] == ["FR2878", "FR2879"]


class TestNoMarkup:
    def test_plain_mail_gives_nothing(self):
        assert extract_flight_reservations(_Email("<p>Your flight FR2878 BGY-ARN</p>")) == []

    def test_lodging_markup_is_not_a_flight(self):
        html = '<div itemscope itemtype="http://schema.org/LodgingReservation"></div>'
        assert extract_flight_reservations(_Email(html)) == []
