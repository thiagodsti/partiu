"""Tests for backend.car_rentals.repository (CRUD over trip_car_rentals)."""

import uuid

from backend.tests.car_rentals.conftest import fetch, row_values, seed_trip, seed_user


class TestCreateAndRead:
    def test_round_trips_every_column(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())

        repo.create(rental_id, trip_id, user_id, row_values())
        rental = repo.get(rental_id, trip_id)

        assert rental is not None
        assert rental.vendor == "Hertz"
        assert rental.pickup.name == "Vienna Airport"
        assert rental.pickup.country_code == "AT"
        assert rental.pickup_date == "2026-03-29"
        assert rental.dropoff_date == "2026-04-01"
        assert rental.booking_reference == "K78806710D9"
        assert rental.vehicle == "Fiat 500 or similar"

    def test_days_counts_local_calendar_dates(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        # 29 March 09:30 to 1 April 23:00 is 86 hours, but three calendar days.
        assert fetch(repo, rental_id, trip_id).days == 3

    def test_a_same_place_rental_is_not_one_way(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        assert fetch(repo, rental_id, trip_id).is_one_way is False

    def test_a_different_dropoff_is_one_way(self, test_db):
        """Two of the three measured bookings were one-way, which is why a
        rental carries two places rather than one."""
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(
            rental_id,
            trip_id,
            user_id,
            row_values(pickup_place="Munich Airport", dropoff_place="Vienna Airport"),
        )

        assert fetch(repo, rental_id, trip_id).is_one_way is True

    def test_list_is_ordered_by_pickup(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        repo.create(
            str(uuid.uuid4()),
            trip_id,
            user_id,
            row_values(pickup_date="2026-04-10", vendor="Sixt"),
        )
        repo.create(str(uuid.uuid4()), trip_id, user_id, row_values())

        assert [r.vendor for r in repo.list_for_trip(trip_id)] == ["Hertz", "Sixt"]

    def test_get_scoped_to_its_trip(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        assert repo.get(rental_id, other_trip) is None


class TestUpdate:
    def test_updates_only_the_given_columns(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        repo.update(rental_id, trip_id, {"vehicle": "VW Golf"})
        rental = fetch(repo, rental_id, trip_id)

        assert rental.vehicle == "VW Golf"
        assert rental.booking_reference == "K78806710D9"

    def test_immutable_columns_are_ignored(self, test_db):
        """A caller cannot rewrite trip_id or created_by through this path."""
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        repo.update(rental_id, trip_id, {"trip_id": other_trip, "created_by": 999})

        assert repo.get(rental_id, trip_id) is not None
        assert repo.get(rental_id, other_trip) is None

    def test_an_empty_update_is_a_no_op(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        repo.update(rental_id, trip_id, {})
        assert fetch(repo, rental_id, trip_id).vendor == "Hertz"


class TestDelete:
    def test_delete_removes_the_row(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        rental_id = str(uuid.uuid4())
        repo.create(rental_id, trip_id, user_id, row_values())

        repo.delete(rental_id, trip_id)
        assert repo.get(rental_id, trip_id) is None


class TestCountByTrip:
    def test_counts_per_trip_in_one_query(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        repo = CarRentalRepository()
        user_id = seed_user(test_db)
        trip_a = seed_trip(test_db, user_id)
        trip_b = seed_trip(test_db, user_id)
        repo.create(str(uuid.uuid4()), trip_a, user_id, row_values())
        repo.create(str(uuid.uuid4()), trip_a, user_id, row_values(vendor="Sixt"))
        repo.create(str(uuid.uuid4()), trip_b, user_id, row_values())

        assert repo.count_by_trip([trip_a, trip_b]) == {trip_a: 2, trip_b: 1}

    def test_no_trips_means_no_query(self, test_db):
        from backend.car_rentals.repository import CarRentalRepository

        assert CarRentalRepository().count_by_trip([]) == {}
