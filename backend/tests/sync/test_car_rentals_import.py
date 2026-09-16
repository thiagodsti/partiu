"""Tests for `sync/car_rentals_import.py` — which trip a hired car belongs to.

The rule reuses `stays_import`'s, widened by one term: "contents" means flights
**and stays**, where the lodging importer looks only at flights. That difference
is the point of the feature — a car is hired precisely on the trips that are not
built out of flights, and the Europcar booking in the corpus is a Sicilian drive.
"""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

_user_counter = itertools.count(1)

RENTAL = {
    "vendor": "Hertz",
    "booking_reference": "X11223344Y",
    "pickup_place": "Vienna Airport",
    "pickup_datetime": "2026-03-29T09:30",
    "dropoff_place": "Vienna Airport",
    "dropoff_datetime": "2026-04-01T23:00",
    "vehicle": "Fiat 500 or similar",
}


class _Email:
    def __init__(self, sender="reservations@emails.hertz.com"):
        self.sender = sender
        self.subject = "My Hertz Reservation"
        self.body = ""
        self.html_body = ""
        self.message_id = f"<{uuid.uuid4()}@example.com>"
        self.date = datetime(2026, 1, 5, tzinfo=UTC)
        self.pdf_attachments = []


def _user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, 'h', 0)",
        (f"rentalimport{next(_user_counter)}",),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _trip(db_path: str, user_id: int, name="Vienna", auto=1) -> str:
    trip_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trips (id, user_id, name, is_auto_generated, booking_refs,
                              created_at, updated_at)
           VALUES (?, ?, ?, ?, '[]', ?, ?)""",
        (trip_id, user_id, name, auto, now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


def _flight(db_path: str, user_id: int, trip_id: str, dep: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO flights (id, user_id, trip_id, flight_number,
                                departure_airport, departure_datetime,
                                arrival_airport, arrival_datetime,
                                created_at, updated_at)
           VALUES (?, ?, ?, 'OS318', 'ARN', ?, 'VIE', ?, 'x', 'x')""",
        (str(uuid.uuid4()), user_id, trip_id, dep, dep),
    )
    conn.commit()
    conn.close()


def _stay(db_path: str, user_id: int, trip_id: str, check_in: str, check_out: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trip_stays (id, trip_id, kind, name,
                                   check_in_datetime, check_in_date,
                                   check_out_datetime, check_out_date,
                                   created_at, updated_at)
           VALUES (?, ?, 'hotel', 'Pensione', ?, ?, ?, ?, 'x', 'x')""",
        (
            str(uuid.uuid4()),
            trip_id,
            f"{check_in}T14:00:00+00:00",
            check_in,
            f"{check_out}T11:00:00+00:00",
            check_out,
        ),
    )
    conn.commit()
    conn.close()


def _rentals(db_path: str, user_id: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT r.*, t.name AS trip_name, t.is_auto_generated
           FROM trip_car_rentals r JOIN trips t ON t.id = r.trip_id
           WHERE t.user_id = ?""",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def _import(user_id: int, rental=None):
    """Run the importer with the parser and the geocoder stubbed out — neither
    is what these tests are about, and the geocoder is a network call."""
    from backend.sync import car_rentals_import

    with (
        patch.object(car_rentals_import, "extract_car_rentals", return_value=[rental or RENTAL]),
        patch.object(car_rentals_import, "_geocode", return_value=(48.11, 16.57, "AT")),
    ):
        return car_rentals_import.import_car_rentals_from_email(_Email(), user_id)


class TestTripMatching:
    def test_joins_the_trip_whose_flights_sit_inside_the_rental(self, test_db):
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id)
        _flight(test_db, user_id, trip_id, "2026-03-29T07:00:00+00:00")

        assert len(_import(user_id)) == 1
        rows = _rentals(test_db, user_id)
        assert len(rows) == 1
        assert rows[0]["trip_id"] == trip_id

    def test_joins_a_trip_that_has_only_stays(self, test_db):
        """The widening that matters: a driving holiday is built out of
        accommodation, and a flights-only rule would be blind on exactly the
        itineraries a rental defines."""
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id, name="Sicily")
        _stay(test_db, user_id, trip_id, "2026-03-29", "2026-04-01")

        _import(user_id)
        assert _rentals(test_db, user_id)[0]["trip_id"] == trip_id

    def test_opens_a_trip_when_nothing_matches(self, test_db):
        user_id = _user(test_db)

        assert len(_import(user_id)) == 1
        row = _rentals(test_db, user_id)[0]
        assert row["is_auto_generated"] == 1
        assert row["trip_name"] == "Vienna Airport (Mar 2026)"

    def test_a_distant_trip_is_not_swallowed(self, test_db):
        """The window is two days, deliberately — the car is collected and
        returned inside the trip, so slack buys nothing and costs neighbours."""
        user_id = _user(test_db)
        far_trip = _trip(test_db, user_id, name="Somewhere else")
        _flight(test_db, user_id, far_trip, "2026-06-01T07:00:00+00:00")

        _import(user_id)
        assert _rentals(test_db, user_id)[0]["trip_id"] != far_trip

    def test_another_users_trip_is_never_joined(self, test_db):
        mine = _user(test_db)
        theirs = _user(test_db)
        their_trip = _trip(test_db, theirs)
        _flight(test_db, theirs, their_trip, "2026-03-29T07:00:00+00:00")

        _import(mine)
        assert _rentals(test_db, mine)[0]["trip_id"] != their_trip


class TestCountryGate:
    """The gate only fires when both sides know and disagree.

    A rental's country comes from geocoding a counter, which is weaker evidence
    than the markup a stay carries, so an unknown on either side passes. The
    failure modes are not symmetric: joining the wrong trip puts a visible row
    on the wrong page, while refusing a true match silently creates a duplicate
    trip beside a perfectly good one.
    """

    @staticmethod
    def _airport(db_path, iata, country):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR REPLACE INTO airports (iata_code, name, country_code) VALUES (?, ?, ?)",
            (iata, f"{iata} Airport", country),
        )
        conn.commit()
        conn.close()

    def test_a_trip_in_another_country_is_not_joined(self, test_db):
        user_id = _user(test_db)
        japan_trip = _trip(test_db, user_id, name="Tokyo")
        self._airport(test_db, "ARN", "JP")
        self._airport(test_db, "VIE", "JP")
        _flight(test_db, user_id, japan_trip, "2026-03-29T07:00:00+00:00")

        _import(user_id)
        assert _rentals(test_db, user_id)[0]["trip_id"] != japan_trip

    def test_a_matching_country_is_joined(self, test_db):
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id)
        self._airport(test_db, "ARN", "SE")
        self._airport(test_db, "VIE", "AT")
        _flight(test_db, user_id, trip_id, "2026-03-29T07:00:00+00:00")

        _import(user_id)
        assert _rentals(test_db, user_id)[0]["trip_id"] == trip_id

    def test_an_airport_with_no_country_recorded_does_not_block(self, test_db):
        """An unranked or missing `airports` row reads as NULL through the LEFT
        JOIN, and must not be treated as a disagreement."""
        user_id = _user(test_db)
        trip_id = _trip(test_db, user_id)
        _flight(test_db, user_id, trip_id, "2026-03-29T07:00:00+00:00")

        _import(user_id)
        assert _rentals(test_db, user_id)[0]["trip_id"] == trip_id


class TestIdempotency:
    def test_the_same_booking_is_not_imported_twice(self, test_db):
        """A rental confirmation is re-read by every full rescan, and is never
        marked processed because it creates no flight."""
        user_id = _user(test_db)

        assert len(_import(user_id)) == 1
        assert _import(user_id) == []
        assert len(_rentals(test_db, user_id)) == 1

    def test_a_booking_with_no_reference_falls_back_to_vendor_and_date(self, test_db):
        user_id = _user(test_db)
        without_ref = {k: v for k, v in RENTAL.items() if k != "booking_reference"}

        assert len(_import(user_id, without_ref)) == 1
        assert _import(user_id, without_ref) == []


class TestStoredValues:
    def test_the_vendor_fields_reach_the_row(self, test_db):
        user_id = _user(test_db)
        _import(user_id)
        row = _rentals(test_db, user_id)[0]

        assert row["vendor"] == "Hertz"
        assert row["booking_reference"] == "X11223344Y"
        assert row["vehicle"] == "Fiat 500 or similar"
        assert row["pickup_country"] == "AT"
        # 09:30 local in Vienna is 07:30Z — the geocoded coordinates are what
        # make that conversion possible.
        assert row["pickup_datetime"].startswith("2026-03-29T07:30")
        assert row["pickup_date"] == "2026-03-29"

    def test_the_trip_span_covers_the_rental(self, test_db):
        user_id = _user(test_db)
        _import(user_id)
        trip_id = _rentals(test_db, user_id)[0]["trip_id"]

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT start_date, end_date FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()
        conn.close()
        assert (row["start_date"], row["end_date"]) == ("2026-03-29", "2026-04-01")


class TestRobustness:
    def test_a_non_rental_email_does_nothing(self, test_db):
        from backend.sync.car_rentals_import import import_car_rentals_from_email

        user_id = _user(test_db)
        assert import_car_rentals_from_email(_Email(sender="noreply@flysas.com"), user_id) == []

    def test_a_geocoder_outage_does_not_lose_the_booking(self, test_db):
        """Without coordinates the rental still saves — it simply has no pin,
        no country and its times are stored as typed."""
        from backend.integrations.photon import client as photon
        from backend.sync import car_rentals_import

        user_id = _user(test_db)
        with (
            patch.object(car_rentals_import, "extract_car_rentals", return_value=[RENTAL]),
            patch.object(photon, "search_places", side_effect=RuntimeError("geocoder down")),
        ):
            created = car_rentals_import.import_car_rentals_from_email(_Email(), user_id)

        assert len(created) == 1
        row = _rentals(test_db, user_id)[0]
        assert row["pickup_country"] is None
        assert row["pickup_datetime"].startswith("2026-03-29T09:30")


class TestThroughTheSyncPipeline:
    """The hook itself: `_process_emails` runs the rental import **ahead of the
    blocked-domain skip**, exactly as it runs the lodging import.

    hertz.com, sixt.com and europcar.com are all on `_NON_FLIGHT_DOMAINS`. They
    are there because they never contain *flights* — and `extract_car_rentals`
    is gated on the sender and on the vendor's own labels, so it finds the
    booking it knows how to read or returns nothing. Without this ordering the
    feature would be dead on arrival for all three vendors.
    """

    HERTZ_BODY = """My Hertz Reservation

Confirmation

X11223344Y

Your Trip Itinerary

Pickup Location

Vienna Airport

Vienna,

AT

Pickup Date & Time

Fri, Mar 29, 2026 at 09:30 AM

Location Hours

Mo-Fr 0700-2330

Drop-off Location

Vienna Airport

Vienna,

AT

Drop-off Date & Time

Mon, Apr 01, 2026 at 11:00 PM
"""

    def test_a_blocked_vendors_confirmation_still_becomes_a_rental(self, test_db):
        from backend.parsers.email_connector import EmailMessage
        from backend.sync import car_rentals_import
        from backend.sync.pipeline import _process_emails, is_non_flight_domain

        user_id = _user(test_db)
        email = EmailMessage(
            message_id=f"<{uuid.uuid4()}@example.com>",
            sender="Hertz <reservations@emails.hertz.com>",
            subject="My Hertz Reservation X11223344Y",
            body=self.HERTZ_BODY,
            date=datetime(2026, 1, 5, tzinfo=UTC),
            html_body="",
            pdf_attachments=[],
        )
        # The premise of this test.
        assert is_non_flight_domain(email.sender) is True

        with patch.object(car_rentals_import, "_geocode", return_value=(48.11, 16.57, "AT")):
            result = _process_emails([email], user_id=user_id)

        assert result["car_rentals_created"] == 1
        row = _rentals(test_db, user_id)[0]
        assert row["vendor"] == "Hertz"
        assert row["booking_reference"] == "X11223344Y"
        assert row["pickup_date"] == "2026-03-29"
        assert row["dropoff_date"] == "2026-04-01"
        assert result["flights_created"] == 0
