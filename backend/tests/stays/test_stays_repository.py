"""Tests for backend.stays.repository — raw CRUD over `trip_stays`."""

import uuid

from backend.tests.stays.conftest import row_values, seed_trip, seed_user


def _repo():
    from backend.stays.repository import StayRepository

    return StayRepository()


class TestCreateAndRead:
    def test_round_trips_every_column(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())

        repo.create(stay_id, trip_id, user_id, row_values(notes="Late arrival"))

        stay = repo.get(stay_id, trip_id)
        assert stay is not None
        assert stay.kind == "hotel"
        assert stay.place.name == "Hotel Avenida Palace"
        assert stay.place.timezone == "Europe/Lisbon"
        assert stay.check_in_date == "2026-10-04"
        assert stay.check_out_date == "2026-10-08"
        assert stay.guests == 2
        assert stay.notes == "Late arrival"
        assert stay.nights == 4

    def test_created_by_username_is_joined(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())

        assert repo.get(stay_id, trip_id).created_by_username.startswith("staytestuser")

    def test_get_is_scoped_to_the_trip(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())

        assert repo.get(stay_id, other_trip) is None

    def test_list_is_ordered_by_check_in_date(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        repo.create(
            str(uuid.uuid4()),
            trip_id,
            user_id,
            row_values(name="Second", check_in_date="2026-10-08", check_out_date="2026-10-10"),
        )
        repo.create(str(uuid.uuid4()), trip_id, user_id, row_values(name="First"))

        assert [s.place.name for s in repo.list_for_trip(trip_id)] == ["First", "Second"]


class TestUpdate:
    def test_updates_only_the_supplied_columns(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())

        repo.update(stay_id, trip_id, {"room_type": "Suite"})

        stay = repo.get(stay_id, trip_id)
        assert stay.room_type == "Suite"
        assert stay.booking_reference == "BK12345"

    def test_immutable_columns_are_ignored(self, test_db):
        """trip_id and created_by are not in `_UPDATABLE`, so a caller cannot
        move a stay onto another trip through this path."""
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())

        repo.update(stay_id, trip_id, {"trip_id": other_trip, "created_by": 999})

        assert repo.get(stay_id, trip_id) is not None
        assert repo.get(stay_id, other_trip) is None

    def test_empty_update_is_a_no_op(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())
        before = repo.get(stay_id, trip_id).updated_at

        repo.update(stay_id, trip_id, {})

        assert repo.get(stay_id, trip_id).updated_at == before


class TestDelete:
    def test_delete_removes_the_row(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())

        repo.delete(stay_id, trip_id)

        assert repo.get(stay_id, trip_id) is None

    def test_delete_is_scoped_to_the_trip(self, test_db):
        repo = _repo()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        stay_id = str(uuid.uuid4())
        repo.create(stay_id, trip_id, user_id, row_values())

        repo.delete(stay_id, other_trip)

        assert repo.get(stay_id, trip_id) is not None
