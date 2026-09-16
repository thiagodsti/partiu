"""Tests for importing schema.org accommodation and attaching it to a trip.

The matching rule these pin was derived from measurement, not taste — see
`sync/stays_import`'s docstring. The cases that matter are the two orderings
real mail actually arrives in: the flights first (the stay joins their trip) and
the stay first by several months (a trip is opened, and the flights must later
join *that* one rather than starting a second).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("test_db")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LODGING_JSON_LD = """{
 "@type": "LodgingReservation",
 "@context": "http://schema.org",
 "reservationNumber": "%(ref)s",
 "reservationStatus": "http://schema.org/ReservationConfirmed",
 "reservationFor": {
  "@type": "LodgingBusiness",
  "name": "%(name)s",
  "address": {
   "@type": "PostalAddress",
   "streetAddress": "1 Example Street",
   "addressLocality": "%(city)s",
   "addressCountry": "%(country)s"
  },
  "telephone": "+000 000 000"
 },
 "checkinDate": "%(checkin)s",
 "checkoutDate": "%(checkout)s"
}"""


class _Email:
    def __init__(self, html_body, sender="Airbnb <automated@airbnb.com>"):
        self.html_body = html_body
        self.body = ""
        self.sender = sender
        self.subject = "Reservation confirmed"
        self.message_id = f"<{uuid.uuid4()}@example.com>"
        self.date = datetime.now(UTC)


def _lodging_email(
    ref="HMREF0001",
    name="Riverside Studio",
    city="Lisbon",
    country="PT",
    checkin="2026-04-10T15:00",
    checkout="2026-04-14T11:00",
    sender="Airbnb <automated@airbnb.com>",
):
    payload = LODGING_JSON_LD % {
        "ref": ref,
        "name": name,
        "city": city,
        "country": country,
        "checkin": checkin,
        "checkout": checkout,
    }
    return _Email(
        f'<html><body><script type="application/ld+json">{payload}</script></body></html>',
        sender=sender,
    )


@pytest.fixture(autouse=True)
def _no_geocoder(monkeypatch):
    """Keep the geocoder out of unit tests.

    Photon is optional by design and a stay saves without coordinates, so
    returning nothing exercises the degraded path the tests care about — and
    guarantees no test ever reaches the public instance over the network.
    """
    from backend.integrations.photon import client as photon

    monkeypatch.setattr(photon, "search_places", lambda *a, **kw: [])


@pytest.fixture
def conn(test_db):
    import backend.database as db_module

    connection = db_module.get_connection(test_db)
    yield connection
    connection.close()


def _make_user(conn, user_id=1, username="traveller"):
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (?,?,?,0,?)",
        (user_id, username, "x", now),
    )
    conn.commit()
    return user_id


def _add_airport(conn, iata, country, city="City"):
    conn.execute(
        "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code) "
        "VALUES (?,?,?,?)",
        (iata, f"{city} Airport", city, country),
    )
    conn.commit()


def _add_flight(conn, user_id, dep, arr, dep_dt, arr_dt, ref="", number="TP100"):
    now = datetime.now(UTC).isoformat()
    fid = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO flights (id, user_id, airline_code, airline_name, flight_number,
              departure_airport, arrival_airport, departure_datetime, arrival_datetime,
              booking_reference, status, is_manually_added, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,'upcoming',0,?,?)""",
        (
            fid,
            user_id,
            number[:2],
            "Test Air",
            number,
            dep,
            arr,
            dep_dt.isoformat(),
            arr_dt.isoformat(),
            ref,
            now,
            now,
        ),
    )
    conn.commit()
    return fid


def _stays(conn, user_id):
    return conn.execute(
        """SELECT s.*, t.name AS trip_name, t.start_date, t.end_date
             FROM trip_stays s JOIN trips t ON t.id = s.trip_id
            WHERE t.user_id = ? ORDER BY s.check_in_date""",
        (user_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlightsFirst:
    """The flights already grouped into a trip; the booking joins it."""

    def test_stay_joins_the_trip_its_flights_belong_to(self, conn):
        from backend.sync.grouping import auto_group_flights
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "LIS", "PT", "Lisbon")
        out = datetime(2026, 4, 10, 6, 0, tzinfo=UTC)
        back = datetime(2026, 4, 14, 16, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "LIS", out, out + timedelta(hours=5), ref="PNR001")
        _add_flight(conn, user_id, "LIS", "ARN", back, back + timedelta(hours=5), ref="PNR001")
        auto_group_flights(user_id=user_id)

        trips_before = conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"]
        created = import_lodging_from_email(_lodging_email(), user_id)

        assert len(created) == 1
        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == trips_before, (
            "the stay should have joined the existing trip, not opened another"
        )
        (stay,) = _stays(conn, user_id)
        assert stay["name"] == "Riverside Studio"
        assert stay["country"] == "PT"
        assert stay["booking_reference"] == "HMREF0001"
        assert stay["kind"] == "airbnb"

    def test_a_trip_in_the_wrong_country_is_not_joined(self, conn):
        """The country gate: a Tokyo trip straddling the same fortnight must not
        swallow a Lisbon booking."""
        from backend.sync.grouping import auto_group_flights
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "HND", "JP", "Tokyo")
        out = datetime(2026, 4, 10, 6, 0, tzinfo=UTC)
        back = datetime(2026, 4, 14, 16, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "HND", out, out + timedelta(hours=12), ref="PNR002")
        _add_flight(conn, user_id, "HND", "ARN", back, back + timedelta(hours=12), ref="PNR002")
        auto_group_flights(user_id=user_id)

        import_lodging_from_email(_lodging_email(), user_id)

        (stay,) = _stays(conn, user_id)
        japan_trip = conn.execute(
            "SELECT id FROM trips WHERE destination_airport = 'ARN' OR origin_airport = 'ARN'"
        ).fetchone()
        assert stay["trip_id"] != japan_trip["id"]
        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == 2


class TestNoTrip:
    """No flights anywhere near — the booking opens its own trip."""

    def test_creates_a_trip_named_for_the_city(self, conn):
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        created = import_lodging_from_email(
            _lodging_email(city="Moneglia", country="IT", name="Moneglia"), user_id
        )
        assert len(created) == 1
        (stay,) = _stays(conn, user_id)
        assert stay["trip_name"] == "Moneglia (Apr 2026)"

    def test_the_new_trip_spans_the_stay(self, conn):
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        import_lodging_from_email(_lodging_email(), user_id)
        (stay,) = _stays(conn, user_id)
        assert stay["start_date"] == "2026-04-10"
        assert stay["end_date"] == "2026-04-14"

    def test_the_new_trip_declares_no_dates_of_its_own(self, conn):
        """An auto-generated trip is described by its contents, so a flight
        arriving later can widen the span rather than fight a declared pair."""
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        import_lodging_from_email(_lodging_email(), user_id)
        row = conn.execute(
            "SELECT planned_start_date, planned_end_date, is_auto_generated FROM trips"
        ).fetchone()
        assert row["planned_start_date"] is None
        assert row["planned_end_date"] is None
        assert row["is_auto_generated"] == 1


class TestStayFirst:
    """The booking arrived months before the tickets — two of six real ones did."""

    def test_later_flights_join_the_stay_created_trip(self, conn):
        from backend.sync.grouping import auto_group_flights
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "LIS", "PT", "Lisbon")

        import_lodging_from_email(_lodging_email(), user_id)
        stay_trip_id = conn.execute("SELECT id FROM trips").fetchone()["id"]

        out = datetime(2026, 4, 10, 6, 0, tzinfo=UTC)
        back = datetime(2026, 4, 14, 16, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "LIS", out, out + timedelta(hours=5), ref="PNR003")
        _add_flight(conn, user_id, "LIS", "ARN", back, back + timedelta(hours=5), ref="PNR003")
        auto_group_flights(user_id=user_id)

        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == 1, (
            "the flights should have joined the stay's trip, not started a second"
        )
        rows = conn.execute("SELECT DISTINCT trip_id FROM flights").fetchall()
        assert [r["trip_id"] for r in rows] == [stay_trip_id]

    def test_joining_flights_do_not_crop_the_stay_out_of_the_span(self, conn):
        """A stay that starts before the outbound must keep its nights: the trip
        span is the union, never just the flights' range."""
        from backend.sync.grouping import auto_group_flights
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "LIS", "PT", "Lisbon")

        import_lodging_from_email(
            _lodging_email(checkin="2026-04-08T15:00", checkout="2026-04-14T11:00"), user_id
        )
        out = datetime(2026, 4, 10, 6, 0, tzinfo=UTC)
        back = datetime(2026, 4, 14, 16, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "LIS", out, out + timedelta(hours=5), ref="PNR004")
        _add_flight(conn, user_id, "LIS", "ARN", back, back + timedelta(hours=5), ref="PNR004")
        auto_group_flights(user_id=user_id)

        trip = conn.execute("SELECT start_date, end_date FROM trips").fetchone()
        assert trip["start_date"] == "2026-04-08", "the stay's first night was cropped"

    def test_a_far_away_trip_is_left_alone(self, conn):
        from backend.sync.grouping import auto_group_flights
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "LIS", "PT", "Lisbon")

        import_lodging_from_email(_lodging_email(), user_id)
        far = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "LIS", far, far + timedelta(hours=5), ref="PNR005")
        _add_flight(
            conn,
            user_id,
            "LIS",
            "ARN",
            far + timedelta(days=5),
            far + timedelta(days=5, hours=5),
            ref="PNR005",
        )
        auto_group_flights(user_id=user_id)

        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == 2


class TestIdempotency:
    def test_reimporting_the_same_booking_creates_nothing(self, conn):
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        assert len(import_lodging_from_email(_lodging_email(), user_id)) == 1
        assert import_lodging_from_email(_lodging_email(), user_id) == []
        assert len(_stays(conn, user_id)) == 1

    def test_a_reference_less_booking_dedupes_on_name_and_date(self, conn):
        """One real record had no reservation number at all."""
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        email = _lodging_email()
        email.html_body = email.html_body.replace('"HMREF0001"', '""')
        assert len(import_lodging_from_email(email, user_id)) == 1
        assert import_lodging_from_email(email, user_id) == []


class TestKind:
    def test_a_non_airbnb_sender_is_a_hotel(self, conn):
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        import_lodging_from_email(
            _lodging_email(sender="Booking.com <noreply@booking.com>"), user_id
        )
        (stay,) = _stays(conn, user_id)
        assert stay["kind"] == "hotel"


class TestBlockedSenderBypass:
    """Airbnb and Booking.com are on `_NON_FLIGHT_DOMAINS`, and must stay there.

    That list exists because *heuristic* parsing of accommodation mail produced
    junk — the same reasoning that removed the generic flight scanners. A
    structural reader is a different thing: it finds a typed LodgingReservation
    or returns nothing, so it runs ahead of the skip while flight extraction
    stays blocked.
    """

    def test_a_blocked_sender_still_has_its_markup_read(self, conn):
        from backend.sync.pipeline import _process_emails, is_non_flight_domain

        user_id = _make_user(conn)
        email = _lodging_email(sender="Airbnb <automated@airbnb.com>")
        assert is_non_flight_domain(email.sender), "precondition: sender is blocked"

        result = _process_emails([email], user_id)

        assert result["stays_created"] == 1
        assert len(_stays(conn, user_id)) == 1

    def test_a_blocked_sender_with_no_markup_still_yields_nothing(self, conn):
        from backend.sync.pipeline import _process_emails

        user_id = _make_user(conn)
        email = _Email(
            "<html><body><p>Your stay is confirmed.</p></body></html>",
            sender="Airbnb <automated@airbnb.com>",
        )
        result = _process_emails([email], user_id)

        assert result["stays_created"] == 0
        assert _stays(conn, user_id) == []
