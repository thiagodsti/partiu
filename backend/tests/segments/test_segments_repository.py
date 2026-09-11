"""Tests for backend.segments.repository (raw CRUD for trip_segments)."""

import uuid

from backend.tests.segments.conftest import row_values, seed_trip, seed_user


class TestCreate:
    def test_create_and_list(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())

        repo.create(segment_id, trip_id, user_id, row_values())

        segments = repo.list_for_trip(trip_id)
        assert len(segments) == 1
        assert segments[0].id == segment_id
        assert segments[0].type == "train"
        assert segments[0].operator == "China Railway"
        assert segments[0].departure.name == "Beijing West Railway Station"
        assert segments[0].departure.timezone == "Asia/Shanghai"
        assert segments[0].created_by == user_id

    def test_created_by_username_is_joined(self, test_db):
        import sqlite3

        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        repo.create(str(uuid.uuid4()), trip_id, user_id, row_values())

        conn = sqlite3.connect(test_db)
        expected = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()[0]
        conn.close()

        assert repo.list_for_trip(trip_id)[0].created_by_username == expected

    def test_list_is_ordered_by_departure(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        repo.create(
            str(uuid.uuid4()),
            trip_id,
            user_id,
            row_values(departure_datetime="2026-10-09T00:00:00+00:00", number="LATER"),
        )
        repo.create(
            str(uuid.uuid4()),
            trip_id,
            user_id,
            row_values(departure_datetime="2026-10-02T00:00:00+00:00", number="EARLIER"),
        )

        assert [s.number for s in repo.list_for_trip(trip_id)] == ["EARLIER", "LATER"]

    def test_places_without_coordinates_round_trip_as_none(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        repo.create(
            str(uuid.uuid4()),
            trip_id,
            user_id,
            row_values(
                departure_lat=None,
                departure_lon=None,
                departure_timezone=None,
            ),
        )

        segment = repo.list_for_trip(trip_id)[0]
        assert segment.departure.lat is None
        assert segment.departure.timezone is None
        # The other end is untouched.
        assert segment.arrival.lat is not None


class TestGet:
    def test_get_returns_segment(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())

        assert repo.get(segment_id, trip_id) is not None

    def test_get_is_scoped_to_the_trip(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())

        assert repo.get(segment_id, other_trip) is None


class TestUpdate:
    def test_update_changes_only_supplied_columns(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())

        repo.update(segment_id, trip_id, {"seat": "Car 8, 4F"})

        segment = repo.get(segment_id, trip_id)
        assert segment is not None
        assert segment.seat == "Car 8, 4F"
        assert segment.operator == "China Railway"

    def test_update_ignores_unknown_and_immutable_keys(self, test_db):
        """trip_id / created_by are not in _UPDATABLE, so a caller cannot move a
        segment to another trip or reassign its author through this path."""
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())

        repo.update(segment_id, trip_id, {"trip_id": other_trip, "created_by": 999, "id": "x"})

        assert repo.get(segment_id, other_trip) is None
        segment = repo.get(segment_id, trip_id)
        assert segment is not None
        assert segment.created_by == user_id

    def test_empty_update_is_a_noop(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())
        before = repo.get(segment_id, trip_id)

        repo.update(segment_id, trip_id, {})

        after = repo.get(segment_id, trip_id)
        assert after is not None and before is not None
        assert after.updated_at == before.updated_at


class TestDelete:
    def test_delete_removes_the_segment(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())

        repo.delete(segment_id, trip_id)

        assert repo.list_for_trip(trip_id) == []

    def test_delete_is_scoped_to_the_trip(self, test_db):
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        other_trip = seed_trip(test_db, user_id)
        segment_id = str(uuid.uuid4())
        repo.create(segment_id, trip_id, user_id, row_values())

        repo.delete(segment_id, other_trip)

        assert len(repo.list_for_trip(trip_id)) == 1


class TestCascade:
    def test_deleting_the_trip_deletes_its_segments(self, test_db):
        from backend.database import db_write
        from backend.segments.repository import SegmentRepository

        repo = SegmentRepository()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        repo.create(str(uuid.uuid4()), trip_id, user_id, row_values())

        with db_write() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))

        assert repo.list_for_trip(trip_id) == []
