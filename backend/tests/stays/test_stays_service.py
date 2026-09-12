"""Tests for backend.stays.service — access checks, validation, local dates."""

import pytest

from backend.tests.stays.conftest import (
    HOTEL_HONOLULU,
    HOTEL_TOKYO,
    seed_trip,
    seed_user,
    stay_payload,
)


def _service():
    from backend.stays.service import StayService

    return StayService()


class TestCreate:
    def test_local_times_are_stored_as_utc(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(trip_id, user_id, stay_payload())

        stay = service.list_stays(trip_id, user_id)[0]
        # Lisbon is UTC+1 in October (WEST), so 15:00 local is 14:00Z.
        assert stay.check_in_datetime.startswith("2026-10-04T14:00:00")
        assert stay.check_out_datetime.startswith("2026-10-08T10:00:00")
        assert stay.place.timezone == "Europe/Lisbon"
        assert stay.nights == 4

    def test_local_date_is_read_at_the_property_not_in_utc(self, test_db):
        """The reason `check_in_date` is a stored column and not `DATE(instant)`.

        15:00 in Honolulu (UTC-10) is 01:00Z the next morning. Deriving the date
        from the UTC instant would file the check-in a day late — widening the
        trip span the wrong way and banding the stay onto the wrong planner day.
        """
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(
            trip_id,
            user_id,
            stay_payload(
                place=dict(HOTEL_HONOLULU),
                check_in_datetime="2026-10-04T15:00",
                check_out_datetime="2026-10-06T11:00",
            ),
        )

        stay = service.list_stays(trip_id, user_id)[0]
        assert stay.place.timezone == "Pacific/Honolulu"
        # The instant really is the 5th in UTC...
        assert stay.check_in_datetime.startswith("2026-10-05T01:00:00")
        # ...but the booking is for the 4th, which is what everything reads.
        assert stay.check_in_date == "2026-10-04"
        assert stay.check_out_date == "2026-10-06"
        assert stay.nights == 2

    def test_nights_count_dates_not_elapsed_hours(self, test_db):
        """15:00 to 11:00 two days later is 44 hours but two nights."""
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(
            trip_id,
            user_id,
            stay_payload(
                place=dict(HOTEL_TOKYO),
                check_in_datetime="2026-10-04T15:00",
                check_out_datetime="2026-10-06T11:00",
            ),
        )

        assert service.list_stays(trip_id, user_id)[0].nights == 2

    def test_place_without_coordinates_is_accepted(self, test_db):
        """An Airbnb usually has no geocodable entry and often no address until
        after booking — it must still save, degrading like a hand-typed station."""
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(
            trip_id,
            user_id,
            stay_payload(kind="airbnb", place={"name": "Ana's flat"}),
        )

        stay = service.list_stays(trip_id, user_id)[0]
        assert stay.place.name == "Ana's flat"
        assert stay.place.lat is None
        assert stay.place.timezone is None
        # With no zone the value was stored as given, so the date round-trips.
        assert stay.check_in_date == "2026-10-04"
        assert stay.nights == 4

    def test_address_is_stored_separately_from_name(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        service.create_stay(trip_id, user_id, stay_payload())

        stay = service.list_stays(trip_id, user_id)[0]
        assert stay.place.name == "Hotel Avenida Palace"
        assert stay.place.address.startswith("R. 1º de Dezembro")


class TestValidation:
    def test_checkout_before_checkin_is_rejected(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="after check-in"):
            service.create_stay(
                trip_id,
                user_id,
                stay_payload(
                    check_in_datetime="2026-10-08T15:00",
                    check_out_datetime="2026-10-04T11:00",
                ),
            )

    def test_checkout_equal_to_checkin_is_rejected(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="after check-in"):
            service.create_stay(
                trip_id,
                user_id,
                stay_payload(
                    check_in_datetime="2026-10-04T15:00",
                    check_out_datetime="2026-10-04T15:00",
                ),
            )

    def test_same_day_checkout_is_allowed(self, test_db):
        """Zero nights is a day-use booking, not a mistake."""
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(
            trip_id,
            user_id,
            stay_payload(
                check_in_datetime="2026-10-04T09:00",
                check_out_datetime="2026-10-04T18:00",
            ),
        )
        assert service.list_stays(trip_id, user_id)[0].nights == 0

    def test_absurdly_long_stay_is_rejected(self, test_db):
        """Catches a mistyped year — the common way this goes wrong."""
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="365 nights"):
            service.create_stay(
                trip_id,
                user_id,
                stay_payload(
                    check_in_datetime="2026-10-04T15:00",
                    check_out_datetime="2028-10-08T11:00",
                ),
            )

    def test_unknown_kind_is_rejected(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="Unsupported stay kind"):
            service.create_stay(trip_id, user_id, stay_payload(kind="yurt"))

    def test_blank_name_is_rejected(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="name is required"):
            service.create_stay(trip_id, user_id, stay_payload(place={"name": "   "}))

    def test_unparseable_datetime_is_rejected(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="check_in_datetime"):
            service.create_stay(trip_id, user_id, stay_payload(check_in_datetime="not a date"))


class TestUpdate:
    def test_partial_update_keeps_untouched_fields(self, test_db):
        """`_build_values` emits a full row, so a PATCH must be merged onto the
        stored stay or every field the client omitted is nulled out."""
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = service.create_stay(trip_id, user_id, stay_payload())

        service.update_stay(trip_id, stay_id, user_id, {"room_type": "Double, sea view"})

        stay = service.list_stays(trip_id, user_id)[0]
        assert stay.room_type == "Double, sea view"
        assert stay.place.name == "Hotel Avenida Palace"
        assert stay.booking_reference == "BK12345"
        assert stay.guests == 2
        assert stay.check_in_date == "2026-10-04"

    def test_moving_only_checkout_validates_against_stored_checkin(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = service.create_stay(trip_id, user_id, stay_payload())

        with pytest.raises(ValueError, match="after check-in"):
            service.update_stay(
                trip_id, stay_id, user_id, {"check_out_datetime": "2026-10-01T11:00"}
            )

    def test_update_recomputes_local_dates(self, test_db):
        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = service.create_stay(trip_id, user_id, stay_payload())

        service.update_stay(trip_id, stay_id, user_id, {"check_out_datetime": "2026-10-11T11:00"})

        stay = service.list_stays(trip_id, user_id)[0]
        assert stay.check_out_date == "2026-10-11"
        assert stay.nights == 7

    def test_unknown_stay_raises(self, test_db):
        from backend.stays.errors import StayNotFoundError

        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(StayNotFoundError):
            service.update_stay(trip_id, "nope", user_id, {"room_type": "Suite"})


class TestAccess:
    def test_other_users_trip_is_refused(self, test_db):
        from backend.stays.errors import TripAccessError

        service = _service()
        owner = seed_user(test_db)
        intruder = seed_user(test_db)
        trip_id = seed_trip(test_db, owner)

        with pytest.raises(TripAccessError):
            service.create_stay(trip_id, intruder, stay_payload())
        with pytest.raises(TripAccessError):
            service.list_stays(trip_id, intruder)


class TestTripSpan:
    def test_stay_extends_a_trip_that_has_no_flights(self, test_db):
        """Accommodation is often booked before transport, so a stays-only trip
        still needs a span — the day planner renders nothing without one."""
        import sqlite3

        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(trip_id, user_id, stay_payload())

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT start_date, end_date FROM trips WHERE id = ?", (trip_id,))
        trip = row.fetchone()
        conn.close()
        assert trip["start_date"] == "2026-10-04"
        assert trip["end_date"] == "2026-10-08"

    def test_deleting_the_last_stay_clears_the_span(self, test_db):
        import sqlite3

        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = service.create_stay(trip_id, user_id, stay_payload())

        service.delete_stay(trip_id, stay_id, user_id)

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        trip = conn.execute(
            "SELECT start_date, end_date FROM trips WHERE id = ?", (trip_id,)
        ).fetchone()
        conn.close()
        assert trip["start_date"] is None
        assert trip["end_date"] is None

    def test_span_uses_the_local_date_not_the_utc_instant(self, test_db):
        """The Honolulu case again, this time end to end through the span SQL."""
        import sqlite3

        service = _service()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_stay(
            trip_id,
            user_id,
            stay_payload(
                place=dict(HOTEL_HONOLULU),
                check_in_datetime="2026-10-04T15:00",
                check_out_datetime="2026-10-06T11:00",
            ),
        )

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        trip = conn.execute("SELECT start_date FROM trips WHERE id = ?", (trip_id,)).fetchone()
        conn.close()
        assert trip["start_date"] == "2026-10-04"
