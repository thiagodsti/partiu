"""Tests for importing schema.org accommodation and attaching it to a trip.

The matching rule these pin was derived from measurement, not taste — see
`sync/stays_import`'s docstring. The cases that matter are the two orderings
real mail actually arrives in: the flights first (the stay joins their trip) and
the stay first by several months (a trip is opened, and the flights must later
join *that* one rather than starting a second).
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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
        """The country gate on the flight window: a Tokyo trip whose flights fall
        near a Lisbon booking must not swallow it. The booking runs past the trip
        (to 16 April), so it is not inside its span either."""
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

        import_lodging_from_email(_lodging_email(checkout="2026-04-16T11:00"), user_id)

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


class TestPlatformMailThroughThePipeline:
    """Airbnb and Booking.com mail goes through the whole pipeline.

    Until migration 0042 both sat on a blocked-sender list and the lodging
    import ran ahead of that skip. The list is gone: a structural reader finds
    a typed LodgingReservation or returns nothing, and the LLM fallback (the
    one reader the list still shielded) is gated on the email's own content.
    """

    def test_the_markup_becomes_a_stay(self, conn):
        from backend.sync.pipeline import _process_emails

        user_id = _make_user(conn)
        email = _lodging_email(sender="Airbnb <automated@airbnb.com>")

        result = _process_emails([email], user_id)

        assert result["stays_created"] == 1
        assert len(_stays(conn, user_id)) == 1

    def test_no_markup_yields_nothing(self, conn):
        from backend.sync.pipeline import _process_emails

        user_id = _make_user(conn)
        email = _Email(
            "<html><body><p>Your stay is confirmed.</p></body></html>",
            sender="Airbnb <automated@airbnb.com>",
        )
        result = _process_emails([email], user_id)

        assert result["stays_created"] == 0
        assert _stays(conn, user_id) == []


class TestBookingComConfirmation:
    """Booking.com carries no markup; its template reader feeds the same import."""

    def test_the_real_confirmation_joins_its_trip(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.grouping import auto_group_flights
        from backend.sync.pipeline import _process_emails

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "LIS", "PT", "Lisbon")
        out = datetime(2026, 12, 22, 8, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "LIS", out, out + timedelta(hours=4), ref="PNR777")
        auto_group_flights(user_id=user_id)
        trips_before = conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"]

        email = load_anonymized_fixture("booking_com_confirmation_anonymized.json")
        result = _process_emails([email], user_id)

        assert result["stays_created"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == trips_before
        (stay,) = _stays(conn, user_id)
        assert stay["name"] == "B&B HOTEL Lisboa Aeroporto"
        assert stay["kind"] == "hotel"
        assert stay["booking_reference"] == "1234567890"
        assert stay["room_type"] == "Double Room"
        assert stay["guests"] == 1
        assert stay["check_in_date"] == "2026-12-22"
        assert stay["check_out_date"] == "2026-12-23"

        # A rescan reads the same mail again and must not duplicate the stay.
        assert _process_emails([email], user_id, skip_dedup=True)["stays_created"] == 0


class TestTripComConfirmation:
    """Trip.com carries no markup either; its template reader feeds the same import."""

    def test_the_real_confirmation_joins_its_trip(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.grouping import auto_group_flights
        from backend.sync.pipeline import _process_emails

        user_id = _make_user(conn)
        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "PEK", "CN", "Beijing")
        out = datetime(2027, 3, 24, 2, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "PEK", out, out + timedelta(hours=9), ref="PNR888")
        auto_group_flights(user_id=user_id)
        trips_before = conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"]

        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        result = _process_emails([email], user_id)

        assert result["stays_created"] == 1
        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == trips_before
        (stay,) = _stays(conn, user_id)
        assert stay["name"] == "Houhaiyuan Hotel (Beijing Gongwangfu Nanluoguxiang Branch)"
        assert stay["kind"] == "hotel"
        assert stay["booking_reference"] == "1234567890123456"
        assert stay["room_type"] == "Guest Room (Double Bed)"
        assert stay["check_in_date"] == "2027-03-24"
        assert stay["check_out_date"] == "2027-03-27"

        # A rescan reads the same mail again and must not duplicate the stay.
        assert _process_emails([email], user_id, skip_dedup=True)["stays_created"] == 0


class TestStayInsideATrip:
    """A stay in the middle of a long trip has no flight near it."""

    def _beijing_trip(self, conn, user_id):
        from backend.sync.grouping import auto_group_flights

        _add_airport(conn, "ARN", "SE", "Stockholm")
        _add_airport(conn, "PEK", "CN", "Beijing")
        out = datetime(2027, 3, 23, 17, 30, tzinfo=UTC)
        back = datetime(2027, 4, 9, 8, 0, tzinfo=UTC)
        _add_flight(conn, user_id, "ARN", "PEK", out, out + timedelta(hours=10), ref="XUOTN4")
        _add_flight(conn, user_id, "PEK", "ARN", back, back + timedelta(hours=11), ref="XUOTN4")
        auto_group_flights(user_id=user_id)
        return conn.execute("SELECT id FROM trips").fetchone()["id"]

    def test_a_mid_trip_stay_joins_the_trip_around_it(self, conn):
        """The Xi'an night of 27 March 2027 used to open a trip of its own."""
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        trip_id = self._beijing_trip(conn, user_id)
        import_lodging_from_email(
            _lodging_email(
                ref="XIAN0001",
                name="Nanfeng Hotel",
                city="Xi'an",
                country="CN",
                checkin="2027-03-27T14:00",
                checkout="2027-03-28T12:00",
            ),
            user_id,
        )
        (stay,) = _stays(conn, user_id)
        assert stay["trip_id"] == trip_id
        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == 1

    def test_a_stay_without_a_country_joins_the_trip_around_it(self, conn):
        """Trip.com confirmations carry no country."""
        from backend.sync.stays_import import _find_trip_for_stay

        user_id = _make_user(conn)
        trip_id = self._beijing_trip(conn, user_id)
        stay = {
            "name": "Nanfeng Hotel",
            "check_in_datetime": "2027-03-27T14:00",
            "check_out_datetime": "2027-03-28T12:00",
            "country_code": None,
        }
        assert _find_trip_for_stay(user_id, stay) == trip_id

    def test_a_stay_in_another_country_mid_trip_still_joins(self, conn):
        """One trip at a time: a Hong Kong night reached by train from Beijing
        is the same trip, whatever the country."""
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        trip_id = self._beijing_trip(conn, user_id)
        import_lodging_from_email(
            _lodging_email(
                ref="HKG0001",
                name="Harbour Hotel",
                city="Hong Kong",
                country="HK",
                checkin="2027-03-30T14:00",
                checkout="2027-04-01T12:00",
            ),
            user_id,
        )
        (stay,) = _stays(conn, user_id)
        assert stay["trip_id"] == trip_id
        assert conn.execute("SELECT COUNT(*) c FROM trips").fetchone()["c"] == 1

    def test_a_stay_running_past_the_trip_is_not_inside_it(self, conn):
        from backend.sync.stays_import import _find_trip_containing_stay

        user_id = _make_user(conn)
        self._beijing_trip(conn, user_id)
        stay = {
            "name": "Late Hotel",
            "check_in_datetime": "2027-04-20T14:00",
            "check_out_datetime": "2027-04-22T12:00",
            "country_code": "CN",
        }
        assert _find_trip_containing_stay(user_id, stay) is None

    def test_the_shortest_trip_around_the_stay_wins(self, conn):
        from backend.sync.stays_import import _find_trip_containing_stay

        user_id = _make_user(conn)
        long_trip = self._beijing_trip(conn, user_id)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO trips (id, name, user_id, start_date, end_date, is_auto_generated,"
            " created_at, updated_at) VALUES ('short', 'Short', ?, '2027-03-26', '2027-03-29', 1, ?, ?)",
            (user_id, now, now),
        )
        conn.commit()
        stay = {
            "name": "Nanfeng Hotel",
            "check_in_datetime": "2027-03-27T14:00",
            "check_out_datetime": "2027-03-28T12:00",
            "country_code": None,
        }
        assert _find_trip_containing_stay(user_id, stay) == "short" != long_trip


class TestPriceBecomesAnExpense:
    """A booking mail's stated total is added to the trip's expenses, once."""

    @staticmethod
    def _expenses(conn):
        return conn.execute(
            "SELECT e.id, e.trip_id, e.description, e.amount, e.currency, e.paid_by_user_id"
            " FROM trip_expenses e ORDER BY e.created_at"
        ).fetchall()

    @staticmethod
    def _participants(conn, expense_id):
        return conn.execute(
            "SELECT * FROM trip_expense_participants WHERE expense_id = ?", (expense_id,)
        ).fetchall()

    def test_the_trip_com_total_is_added_to_the_trip(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        (stay_id,) = import_lodging_from_email(email, user_id)

        (expense,) = self._expenses(conn)
        stay = conn.execute("SELECT * FROM trip_stays WHERE id = ?", (stay_id,)).fetchone()
        assert expense["trip_id"] == stay["trip_id"]
        assert expense["description"] == stay["name"]
        assert (expense["amount"], expense["currency"]) == (2003.0, "SEK")
        assert expense["paid_by_user_id"] == user_id
        assert (stay["price_amount"], stay["price_currency"]) == (2003.0, "SEK")

    def test_the_expense_is_charged_to_the_importer_alone(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        email = load_anonymized_fixture("booking_com_confirmation_anonymized.json")
        import_lodging_from_email(email, user_id)

        (expense,) = self._expenses(conn)
        assert (expense["amount"], expense["currency"]) == (69.23, "EUR")
        (participant,) = self._participants(conn, expense["id"])
        assert participant["user_id"] == user_id

    def test_reimporting_adds_no_second_expense(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        import_lodging_from_email(email, user_id)
        import_lodging_from_email(email, user_id)
        assert len(self._expenses(conn)) == 1

    def test_a_stay_imported_before_prices_gets_its_expense_on_rescan(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        import_lodging_from_email(email, user_id)
        conn.execute("DELETE FROM trip_expenses")
        conn.execute("UPDATE trip_stays SET price_amount = NULL, price_currency = NULL")
        conn.commit()

        assert import_lodging_from_email(email, user_id) == []
        (expense,) = self._expenses(conn)
        assert expense["amount"] == 2003.0

    def test_a_deleted_expense_does_not_come_back(self, conn):
        from conftest import load_anonymized_fixture

        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        import_lodging_from_email(email, user_id)
        conn.execute("DELETE FROM trip_expenses")
        conn.commit()

        import_lodging_from_email(email, user_id)
        assert self._expenses(conn) == []

    def test_a_mail_without_a_price_adds_no_expense(self, conn):
        from backend.sync.stays_import import import_lodging_from_email

        user_id = _make_user(conn)
        (stay_id,) = import_lodging_from_email(_lodging_email(), user_id)
        assert self._expenses(conn) == []
        stay = conn.execute("SELECT * FROM trip_stays WHERE id = ?", (stay_id,)).fetchone()
        assert stay["price_amount"] is None

    def test_a_failed_expense_leaves_no_price_behind(self, conn, monkeypatch):
        from conftest import load_anonymized_fixture

        from backend.expenses.service import ExpenseService
        from backend.sync.stays_import import import_lodging_from_email

        real = ExpenseService.create_expense
        calls = []

        def fail_once(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("db down")
            return real(self, *args, **kwargs)

        monkeypatch.setattr(ExpenseService, "create_expense", fail_once)
        user_id = _make_user(conn)
        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        import_lodging_from_email(email, user_id)

        (stay,) = _stays(conn, user_id)
        assert stay["price_amount"] is None
        import_lodging_from_email(email, user_id)
        assert len(self._expenses(conn)) == 1


class TestPlacingOnRescan:
    """A stay imported without a pin gets one when its mail is read again."""

    BEIJING = {
        "前井胡同": [
            {
                "name": "Qianjing",
                "city": "Beijing",
                "countrycode": "CN",
                "country": "China",
                "address": "",
                "lat": 39.9365,
                "lon": 116.3839,
            }
        ]
    }

    def _import(self, conn, user_id, answers):
        from conftest import load_anonymized_fixture

        from backend.integrations.photon import client as photon
        from backend.sync.stays_import import import_lodging_from_email

        email = load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")
        with (
            patch.object(photon, "is_configured", return_value=True),
            patch.object(photon, "search_places", side_effect=lambda q, **kw: answers.get(q, [])),
        ):
            return import_lodging_from_email(email, user_id)

    def test_the_local_street_places_it_and_its_times_move_to_beijing(self, conn):
        user_id = _make_user(conn)
        (stay_id,) = self._import(conn, user_id, {})
        before = conn.execute("SELECT * FROM trip_stays WHERE id = ?", (stay_id,)).fetchone()
        assert before["lat"] is None

        assert self._import(conn, user_id, self.BEIJING) == []
        after = conn.execute("SELECT * FROM trip_stays WHERE id = ?", (stay_id,)).fetchone()
        assert (after["lat"], after["lon"]) == (39.9365, 116.3839)
        # 14:00 at the hotel is 06:00 UTC in Beijing (UTC+8); the dates hold.
        assert after["check_in_datetime"].startswith("2027-03-24T06:00")
        assert (after["check_in_date"], after["check_out_date"]) == ("2027-03-24", "2027-03-27")

    def test_a_place_already_on_the_map_is_left_alone(self, conn):
        user_id = _make_user(conn)
        (stay_id,) = self._import(conn, user_id, self.BEIJING)
        conn.execute("UPDATE trip_stays SET lat = 1.0, lon = 2.0 WHERE id = ?", (stay_id,))
        conn.commit()
        moved = {"前井胡同": [{**self.BEIJING["前井胡同"][0], "lat": 50.0, "lon": 50.0}]}
        self._import(conn, user_id, moved)
        row = conn.execute("SELECT lat, lon FROM trip_stays WHERE id = ?", (stay_id,)).fetchone()
        assert (row["lat"], row["lon"]) == (1.0, 2.0)
