"""Tests for backend.car_rentals.service — validation, local→UTC conversion, and
the denormalised local dates the trip span and day planner are built on."""

import pytest

from backend.tests.car_rentals.conftest import (
    COUNTER_HONOLULU,
    COUNTER_MUNICH,
    COUNTER_VIENNA,
    fetch,
    rental_payload,
    seed_trip,
    seed_user,
)


class TestCreate:
    def test_local_time_is_converted_to_utc_at_the_counter(self, test_db):
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        rental_id = service.create_rental(trip_id, user_id, rental_payload())
        rental = fetch(service._repository, rental_id, trip_id)

        # 09:30 in Vienna on 29 March 2026 is CEST (UTC+2).
        assert rental.pickup_datetime.startswith("2026-03-29T07:30")
        assert rental.pickup.timezone == "Europe/Vienna"

    def test_each_end_keeps_its_own_zone_on_a_one_way(self, test_db):
        """A one-way rental can cross a zone, which is why both ends carry
        their own timezone and their own local date."""
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        rental_id = service.create_rental(
            trip_id,
            user_id,
            rental_payload(pickup=dict(COUNTER_MUNICH), dropoff=dict(COUNTER_VIENNA)),
        )
        rental = fetch(service._repository, rental_id, trip_id)

        assert rental.pickup.timezone == "Europe/Berlin"
        assert rental.dropoff.timezone == "Europe/Vienna"
        assert rental.is_one_way is True

    def test_the_local_date_is_the_date_at_the_counter(self, test_db):
        """The whole reason the dates are denormalised: an 18:00 drop-off in
        Honolulu is 04:00Z the *next* day, so a span or planner band derived
        from DATE(dropoff_datetime) would land a day late."""
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        rental_id = service.create_rental(
            trip_id,
            user_id,
            rental_payload(
                pickup=dict(COUNTER_HONOLULU),
                dropoff=dict(COUNTER_HONOLULU),
                pickup_datetime="2026-03-29T09:00",
                dropoff_datetime="2026-04-01T18:00",
            ),
        )
        rental = fetch(service._repository, rental_id, trip_id)

        assert rental.dropoff_datetime.startswith("2026-04-02T04:00")
        assert rental.dropoff_date == "2026-04-01"

    def test_a_counter_typed_by_hand_still_saves(self, test_db):
        """No coordinates means no pin and no zone conversion — not a refusal.
        Same contract as a hand-typed station or property."""
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        rental_id = service.create_rental(
            trip_id,
            user_id,
            rental_payload(
                pickup={"name": "Some back-street garage"},
                dropoff={"name": "Some back-street garage"},
            ),
        )
        rental = fetch(service._repository, rental_id, trip_id)

        assert rental.pickup.timezone is None
        assert rental.pickup_datetime.startswith("2026-03-29T09:30")

    def test_the_rental_extends_the_trip_span(self, test_db):
        """A rental is never validated against the trip's dates — it widens
        them, exactly as a stay does."""
        from backend.car_rentals.service import CarRentalService
        from backend.database import db_conn

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_rental(trip_id, user_id, rental_payload())

        with db_conn() as conn:
            row = conn.execute(
                "SELECT start_date, end_date FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        assert row["start_date"] == "2026-03-29"
        assert row["end_date"] == "2026-04-01"


class TestValidation:
    def test_dropoff_before_pickup_is_refused(self, test_db):
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="after pickup"):
            service.create_rental(
                trip_id,
                user_id,
                rental_payload(
                    pickup_datetime="2026-04-01T09:00", dropoff_datetime="2026-03-29T09:00"
                ),
            )

    def test_a_rental_over_a_year_is_refused(self, test_db):
        """A mistyped year, not a lease."""
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="365"):
            service.create_rental(
                trip_id,
                user_id,
                rental_payload(
                    pickup_datetime="2026-03-29T09:00", dropoff_datetime="2028-03-29T09:00"
                ),
            )

    def test_a_nameless_counter_is_refused(self, test_db):
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="place name is required"):
            service.create_rental(trip_id, user_id, rental_payload(pickup={"name": "  "}))

    def test_a_vendorless_rental_is_refused(self, test_db):
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="Vendor is required"):
            service.create_rental(trip_id, user_id, rental_payload(vendor=" "))

    def test_an_unparseable_datetime_is_refused(self, test_db):
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="not a valid datetime"):
            service.create_rental(trip_id, user_id, rental_payload(pickup_datetime="soon"))


class TestUpdate:
    def test_a_one_field_patch_keeps_everything_else(self, test_db):
        """`_build_values` always emits a full row, so without the merge a PATCH
        of one field would null the rest — the trap `SegmentService` documents."""
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = service.create_rental(trip_id, user_id, rental_payload())

        service.update_rental(trip_id, rental_id, user_id, {"vehicle": "VW Golf"})
        rental = fetch(service._repository, rental_id, trip_id)

        assert rental.vehicle == "VW Golf"
        assert rental.vendor == "Hertz"
        assert rental.booking_reference == "K78806710D9"
        assert rental.pickup.name == "Vienna Airport"
        assert rental.pickup_datetime.startswith("2026-03-29T07:30")

    def test_a_patched_dropoff_is_validated_against_the_stored_pickup(self, test_db):
        """The second half of the same trap: without the merge the new drop-off
        would be validated against nothing at all."""
        from backend.car_rentals.service import CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = service.create_rental(trip_id, user_id, rental_payload())

        with pytest.raises(ValueError, match="after pickup"):
            service.update_rental(
                trip_id, rental_id, user_id, {"dropoff_datetime": "2026-03-28T10:00"}
            )

    def test_updating_an_unknown_rental_raises(self, test_db):
        from backend.car_rentals.service import CarRentalNotFoundError, CarRentalService

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(CarRentalNotFoundError):
            service.update_rental(trip_id, "nope", user_id, {"vehicle": "x"})


class TestDelete:
    def test_delete_recomputes_the_span(self, test_db):
        from backend.car_rentals.service import CarRentalService
        from backend.database import db_conn

        service = CarRentalService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = service.create_rental(trip_id, user_id, rental_payload())

        service.delete_rental(trip_id, rental_id, user_id)

        with db_conn() as conn:
            row = conn.execute(
                "SELECT start_date, end_date FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        assert row["start_date"] is None
        assert row["end_date"] is None


class TestAccess:
    def test_another_users_trip_is_refused(self, test_db):
        from backend.car_rentals.service import CarRentalService, TripAccessError

        service = CarRentalService()
        owner = seed_user(test_db)
        stranger = seed_user(test_db)
        trip_id = seed_trip(test_db, owner)

        with pytest.raises(TripAccessError):
            service.list_rentals(trip_id, stranger)
        with pytest.raises(TripAccessError):
            service.create_rental(trip_id, stranger, rental_payload())
