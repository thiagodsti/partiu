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

    def test_an_ambiguous_city_does_not_confirm_the_airport(self, use, seeded_airports_db):
        # "Milan" is Linate and Malpensa: it cannot vouch for MXP.
        leg = json.loads(json.dumps(_LEG))
        leg["reservationFor"]["arrivalAirport"] = {"@type": "Airport", "iataCode": "MXP"}
        use(json.dumps([leg]))
        email = _email(body="U2 8205 London Stansted (STN) 07:05, arriving Milan 09:50")
        assert kitinerary.extract_kitinerary_flights(email) == []

    def test_the_airport_s_own_name_confirms_it(self, use, seeded_airports_db):
        leg = json.loads(json.dumps(_LEG))
        leg["reservationFor"]["arrivalAirport"] = {"@type": "Airport", "iataCode": "MXP"}
        use(json.dumps([leg]))
        email = _email(body="U2 8205 London Stansted (STN) 07:05, arriving Milan Malpensa 09:50")
        assert len(kitinerary.extract_kitinerary_flights(email)) == 1

    def test_without_airport_data_nothing_is_confirmed(self, use, seeded_airports_db):
        use(json.dumps([_LEG]))
        with patch(
            "backend.parsers.airport_grounding.airport_index",
            return_value=(frozenset(), {}, {}),
        ):
            assert kitinerary.extract_kitinerary_flights(_email()) == []

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


# ---------------------------------------------------------------------------
# Beyond flights. The train, bus, rental-car and event records below are KDE
# Itinerary's own test fixtures (autotests/extractordata/sncf, regiojet,
# calendarhandlerdata, ical in the KItinerary repository); the ferry,
# restaurant and attraction ones follow schema.org, as KDE has no sample.
# ---------------------------------------------------------------------------

_SNCF_TRAIN = {
    "@type": "TrainReservation",
    "reservationFor": {
        "@type": "TrainTrip",
        "arrivalStation": {"@type": "TrainStation", "name": "MONTPELLIER ST-RO"},
        "arrivalTime": "2018-07-15T19:58:00",
        "departureDay": "2018-07-15",
        "departureStation": {"@type": "TrainStation", "name": "TOULOUSE MATABIAU"},
        "departureTime": "2018-07-15T17:50:00",
        "trainNumber": "6857",
    },
    "reservationNumber": "XXX007",
    "reservationStatus": "http://schema.org/ReservationConfirmed",
    "reservedTicket": {
        "@type": "Ticket",
        "ticketedSeat": {"@type": "Seat", "seatNumber": "31", "seatSection": "13"},
    },
}
_SNCF_TEXT = "TOULOUSE MATABIAU 17h50 -> MONTPELLIER ST-RO 19h58, TGV 6857, voiture 13 place 31"

_REGIOJET_BUS = {
    "@type": "BusReservation",
    "reservationFor": {
        "@type": "BusTrip",
        "arrivalBusStop": {"@type": "BusStation", "name": "Brno, AN u hotelu Grand"},
        "arrivalTime": "2015-08-01T00:30:00",
        "busName": "Vienna → Prague",
        "busNumber": "SA",
        "departureBusStop": {"@type": "BusStation", "name": "Wien, Schwechat Airport Bbf."},
        "departureTime": "2015-07-31T22:10:00",
    },
    "reservationNumber": "0123456789",
    "reservedTicket": {"@type": "Ticket", "ticketedSeat": {"@type": "Seat", "seatNumber": "48"}},
}
_REGIOJET_TEXT = "Wien, Schwechat Airport Bbf. 22:10 -> Brno, AN u hotelu Grand 00:30, seat 48"

_FERRY = {
    "@type": "BoatReservation",
    "reservationFor": {
        "@type": "BoatTrip",
        "departureBoatTerminal": {
            "@type": "BoatTerminal",
            "name": "Stockholm Värtahamnen",
            "geo": {"latitude": 59.35, "longitude": 18.1},
            "address": {"addressCountry": "SE"},
        },
        "arrivalBoatTerminal": {"@type": "BoatTerminal", "name": "Helsinki Olympia"},
        "departureTime": {"@type": "QDateTime", "@value": "2026-06-01T16:45:00+02:00"},
        "arrivalTime": {"@type": "QDateTime", "@value": "2026-06-02T10:30:00+03:00"},
    },
    "reservationNumber": "FERRY1",
}
_FERRY_TEXT = "Stockholm Värtahamnen 16:45 → Helsinki Olympia 10:30"

_RENTAL = {
    "@type": "RentalCarReservation",
    "reservationNumber": "546323",
    "underName": {"@type": "Person", "name": "John Smith"},
    "reservationFor": {
        "@type": "RentalCar",
        "name": "Economy Class Car",
        "model": "Civic",
        "brand": {"@type": "Brand", "name": "Honda"},
        "rentalCompany": {"@type": "Organization", "name": "Avis"},
    },
    "pickupLocation": {
        "@type": "Place",
        "name": "Avis San Diego Airport",
        "address": {"addressLocality": "San Diego", "addressCountry": "US"},
    },
    "pickupTime": "2027-08-05T16:00:00-07:00",
    "dropoffLocation": {
        "@type": "Place",
        "name": "Avis LAX",
        "address": {"addressLocality": "Los Angeles", "addressCountry": "US"},
    },
    "dropoffTime": "2027-08-06T20:00:00-07:00",
}

_EVENT = {
    "@type": "EventReservation",
    "reservationFor": {
        "@type": "Event",
        "name": "Akademy 2019",
        "location": {
            "@type": "Place",
            "name": "University of Milano-Bicocca",
            "address": {"addressCountry": "IT", "addressLocality": "Milan"},
        },
        "startDate": {
            "@type": "QDateTime",
            "@value": "2019-09-07T09:30:00+02:00",
            "timezone": "Europe/Rome",
        },
    },
    "reservationNumber": "42",
    "reservationStatus": "http://schema.org/ReservationConfirmed",
}


class TestGroundLegs:
    def test_a_train_ticket_becomes_a_train_leg(self):
        (leg,) = kitinerary.ground_legs_from_items([_SNCF_TRAIN], _SNCF_TEXT)
        assert leg["type"] == "train"
        assert leg["number"] == "6857"
        assert leg["booking_reference"] == "XXX007"
        assert leg["departure"]["name"] == "TOULOUSE MATABIAU"
        assert leg["arrival"]["name"] == "MONTPELLIER ST-RO"
        assert (leg["departure_datetime"], leg["arrival_datetime"]) == (
            "2018-07-15T17:50",
            "2018-07-15T19:58",
        )
        assert leg["seat"] == "Coach 13, seat 31"

    def test_a_bus_ticket_keeps_its_service_and_seat(self):
        (leg,) = kitinerary.ground_legs_from_items([_REGIOJET_BUS], _REGIOJET_TEXT)
        assert (leg["type"], leg["number"], leg["seat"]) == ("bus", "SA", "48")
        assert leg["arrival_datetime"] == "2015-08-01T00:30"

    def test_a_ferry_keeps_coordinates_country_and_local_clocks(self):
        (leg,) = kitinerary.ground_legs_from_items([_FERRY], _FERRY_TEXT)
        assert leg["type"] == "ferry"
        assert (leg["departure"]["lat"], leg["departure"]["country_code"]) == (59.35, "SE")
        # Each end's wall clock, offsets dropped: the importer localises them.
        assert (leg["departure_datetime"], leg["arrival_datetime"]) == (
            "2026-06-01T16:45",
            "2026-06-02T10:30",
        )

    def test_a_station_the_email_does_not_name_is_refused(self):
        assert kitinerary.ground_legs_from_items([_SNCF_TRAIN], "Votre billet TGV 6857") == []

    def test_cancelled_or_timeless_legs_are_refused(self):
        cancelled = {**_SNCF_TRAIN, "reservationStatus": "http://schema.org/ReservationCancelled"}
        no_time = json.loads(json.dumps(_SNCF_TRAIN))
        no_time["reservationFor"]["departureTime"] = "2018-07-15"
        assert kitinerary.ground_legs_from_items([cancelled, no_time], _SNCF_TEXT) == []

    def test_one_leg_per_passenger_is_kept_once(self):
        assert len(kitinerary.ground_legs_from_items([_SNCF_TRAIN, _SNCF_TRAIN], _SNCF_TEXT)) == 1

    def test_flights_are_not_ground_legs(self):
        assert kitinerary.ground_legs_from_items([_LEG], "STN LIS") == []


class TestStaysRentalsAndBookings:
    def test_a_lodging_reservation_keeps_its_coordinates(self):
        stay = {
            "@type": "LodgingReservation",
            "reservationFor": {
                "@type": "LodgingBusiness",
                "name": "Hotel Example",
                "geo": {"latitude": 38.71, "longitude": -9.14},
                "address": {"streetAddress": "Rua X 1", "addressCountry": "PT"},
            },
            "checkinTime": "2026-05-01T15:00:00+01:00",
            "checkoutTime": "2026-05-03T11:00:00+01:00",
            "reservationNumber": "H123",
        }
        (s,) = kitinerary.stays_from_items([stay])
        assert (s["name"], s["country_code"], s["lat"], s["lon"]) == (
            "Hotel Example",
            "PT",
            38.71,
            -9.14,
        )
        assert (s["check_in_datetime"], s["check_out_datetime"]) == (
            "2026-05-01T15:00",
            "2026-05-03T11:00",
        )

    def test_a_rental_car_becomes_a_rental(self):
        (r,) = kitinerary.rentals_from_items([_RENTAL])
        assert r["vendor"] == "Avis"
        assert (r["pickup_place"], r["dropoff_place"]) == ("Avis San Diego Airport", "Avis LAX")
        assert (r["pickup_datetime"], r["dropoff_datetime"]) == (
            "2027-08-05T16:00",
            "2027-08-06T20:00",
        )
        assert (r["vehicle"], r["driver_name"], r["booking_reference"]) == (
            "Honda Civic",
            "John Smith",
            "546323",
        )

    def test_an_event_becomes_a_booked_planner_item(self):
        (b,) = kitinerary.bookings_from_items([_EVENT, _EVENT])  # one ticket per attendee
        assert b == {
            "title": "Akademy 2019",
            "date": "2019-09-07",
            "time": "09:30",
            "place_name": "University of Milano-Bicocca",
            "lat": None,
            "lon": None,
            "notes": "Booking 42",
        }

    def test_restaurant_and_attraction_bookings(self):
        dinner = {
            "@type": "FoodEstablishmentReservation",
            "reservationFor": {
                "@type": "FoodEstablishment",
                "name": "Blue Nile",
                "geo": {"latitude": 52.49776, "longitude": 13.3872},
            },
            "startTime": "2026-04-10T20:00:00+02:00",
        }
        museum = {
            "@type": "TouristAttractionVisit",
            "touristAttraction": {"@type": "TouristAttraction", "name": "Vasa Museum"},
            "arrivalTime": "2026-04-11T10:00:00",
        }
        got = {b["title"]: b for b in kitinerary.bookings_from_items([dinner, museum])}
        assert (got["Blue Nile"]["date"], got["Blue Nile"]["time"], got["Blue Nile"]["lat"]) == (
            "2026-04-10",
            "20:00",
            52.49776,
        )
        assert (got["Vasa Museum"]["date"], got["Vasa Museum"]["time"]) == ("2026-04-11", "10:00")

    def test_a_booking_without_a_time_is_skipped(self):
        no_time = json.loads(json.dumps(_EVENT))
        no_time["reservationFor"]["startDate"] = "2019-09-07"
        assert kitinerary.bookings_from_items([no_time]) == []

    def test_the_extractor_runs_once_per_email(self, use):
        log = use(json.dumps([_SNCF_TRAIN]))
        email = _email(body=_SNCF_TEXT)
        kitinerary.extract_kitinerary_ground_legs(email)
        log.unlink()
        kitinerary.extract_kitinerary_bookings(email)
        kitinerary.extract_kitinerary_flights(email)
        assert not log.exists(), "a second subprocess ran for the same email"


class TestReviewFollowUps:
    def test_stations_named_only_in_the_html_still_count(self, use):
        use(json.dumps([_SNCF_TRAIN]))
        email = _email(body="Your ticket is attached.", html_body=f"<p>{_SNCF_TEXT}</p>")
        assert len(kitinerary.extract_kitinerary_ground_legs(email)) == 1

    def test_stations_named_nowhere_are_still_refused(self, use):
        use(json.dumps([_SNCF_TRAIN]))
        email = _email(body="Your ticket is attached.", html_body="<p>Bon voyage</p>")
        assert kitinerary.extract_kitinerary_ground_legs(email) == []

    def test_a_rental_without_a_stated_return_location_is_refused(self):
        no_dropoff = {k: v for k, v in _RENTAL.items() if k != "dropoffLocation"}
        assert kitinerary.rentals_from_items([no_dropoff]) == []
