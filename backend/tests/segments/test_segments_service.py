"""Tests for backend.segments.service — access checks, validation, local→UTC."""

import pytest

from backend.tests.segments.conftest import (
    PARIS_NORD,
    XIAN_NORTH,
    seed_trip,
    seed_user,
    segment_payload,
)


class TestCreate:
    def test_local_times_are_stored_as_utc(self, test_db):
        """08:00 at Beijing West is 00:00 UTC — the conversion has to come from
        the station's own coordinates, since there is no IATA code to look up."""
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(trip_id, user_id, segment_payload())

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure_datetime.startswith("2026-10-04T00:00:00")
        assert segment.arrival_datetime.startswith("2026-10-04T04:30:00")
        assert segment.departure.timezone == "Asia/Shanghai"
        assert segment.duration_minutes == 270

    def test_cross_timezone_duration_is_real_elapsed_time(self, test_db):
        """Each end is converted with its own offset, so the stored duration is
        real elapsed time and not a subtraction of two unrelated wall clocks.

        Paris 08:00 CEST (UTC+2) is 06:00Z; Xi'an 12:30 CST (UTC+8) the next day
        is 04:30Z. That is 22h30 elapsed — reading the clock faces alone would
        say 28h30.
        """
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(
            trip_id,
            user_id,
            segment_payload(
                departure=dict(PARIS_NORD),
                arrival=dict(XIAN_NORTH),
                departure_datetime="2026-10-04T08:00",
                arrival_datetime="2026-10-05T12:30",
            ),
        )

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure.timezone == "Europe/Paris"
        assert segment.arrival.timezone == "Asia/Shanghai"
        assert segment.departure_datetime.startswith("2026-10-04T06:00:00")
        assert segment.arrival_datetime.startswith("2026-10-05T04:30:00")
        assert segment.duration_minutes == 22 * 60 + 30

    def test_place_without_coordinates_is_accepted(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(
            trip_id,
            user_id,
            segment_payload(
                type="bus",
                departure={"name": "Village bus stop"},
                arrival={"name": "Another village"},
            ),
        )

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure.lat is None
        assert segment.departure.timezone is None
        # With no zone to apply, the time is stored as given rather than guessed.
        assert segment.departure_datetime.startswith("2026-10-04T08:00:00")

    def test_rejects_unknown_type(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="Unsupported segment type"):
            service.create_segment(trip_id, user_id, segment_payload(type="teleport"))

    def test_rejects_arrival_before_departure(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="Arrival must not be before departure"):
            service.create_segment(
                trip_id, user_id, segment_payload(arrival_datetime="2026-10-04T07:00")
            )

    def test_rejects_blank_place_name(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="required"):
            service.create_segment(trip_id, user_id, segment_payload(departure={"name": "   "}))

    def test_rejects_unparseable_datetime(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(ValueError, match="departure_datetime"):
            service.create_segment(
                trip_id, user_id, segment_payload(departure_datetime="tomorrow-ish")
            )

    def test_type_is_normalised(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(trip_id, user_id, segment_payload(type="  TRAIN "))

        assert service.list_segments(trip_id, user_id)[0].type == "train"

    def test_blank_optional_fields_become_none(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(trip_id, user_id, segment_payload(operator="   ", seat=""))

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.operator is None
        assert segment.seat is None


class TestUpdate:
    def test_partial_update_keeps_untouched_fields(self, test_db):
        """A PATCH of one field must not null out the rest — _build_values always
        emits a full row, so the service merges onto the stored segment first."""
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = service.create_segment(trip_id, user_id, segment_payload())

        service.update_segment(trip_id, segment_id, user_id, {"seat": "Car 8, 4F"})

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.seat == "Car 8, 4F"
        assert segment.operator == "China Railway"
        assert segment.number == "G87"
        assert segment.departure.name == "Beijing West Railway Station"

    def test_moving_only_the_arrival_time_keeps_departure(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = service.create_segment(trip_id, user_id, segment_payload())

        service.update_segment(
            trip_id, segment_id, user_id, {"arrival_datetime": "2026-10-04T13:15"}
        )

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure_datetime.startswith("2026-10-04T00:00:00")
        assert segment.duration_minutes == 315

    def test_partial_update_is_validated_against_stored_other_end(self, test_db):
        """Moving only the arrival earlier than the stored departure must fail."""
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = service.create_segment(trip_id, user_id, segment_payload())

        with pytest.raises(ValueError, match="Arrival must not be before departure"):
            service.update_segment(
                trip_id, segment_id, user_id, {"arrival_datetime": "2026-10-04T06:00"}
            )

    def test_unknown_segment_raises(self, test_db):
        from backend.segments.errors import SegmentNotFoundError
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(SegmentNotFoundError):
            service.update_segment(trip_id, "no-such-id", user_id, {"seat": "1A"})


class TestDelete:
    def test_delete_removes_it(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = service.create_segment(trip_id, user_id, segment_payload())

        service.delete_segment(trip_id, segment_id, user_id)

        assert service.list_segments(trip_id, user_id) == []

    def test_unknown_segment_raises(self, test_db):
        from backend.segments.errors import SegmentNotFoundError
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        with pytest.raises(SegmentNotFoundError):
            service.delete_segment(trip_id, "no-such-id", user_id)


class TestAccess:
    def test_another_users_trip_is_refused(self, test_db):
        from backend.segments.errors import TripAccessError
        from backend.segments.service import SegmentService

        service = SegmentService()
        owner_id = seed_user(test_db)
        intruder_id = seed_user(test_db)
        trip_id = seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_segments(trip_id, intruder_id)
        with pytest.raises(TripAccessError):
            service.create_segment(trip_id, intruder_id, segment_payload())

    def test_accepted_collaborator_has_access(self, test_db):
        from backend.database import db_write
        from backend.segments.service import SegmentService

        service = SegmentService()
        owner_id = seed_user(test_db)
        collaborator_id = seed_user(test_db)
        trip_id = seed_trip(test_db, owner_id)
        with db_write() as conn:
            conn.execute(
                "INSERT INTO trip_shares (trip_id, user_id, invited_by, status) "
                "VALUES (?, ?, ?, 'accepted')",
                (trip_id, collaborator_id, owner_id),
            )

        segment_id = service.create_segment(trip_id, collaborator_id, segment_payload())

        assert len(service.list_segments(trip_id, owner_id)) == 1
        service.delete_segment(trip_id, segment_id, collaborator_id)


class TestTripSpan:
    """A segment has to widen the trip's date range, or the day planner — which
    renders one card per day between start_date and end_date — has no card for a
    day that holds only a train."""

    @staticmethod
    def _span(trip_id: str) -> tuple[str | None, str | None]:
        from backend.database import db_conn

        with db_conn() as conn:
            row = conn.execute(
                "SELECT start_date, end_date FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        return (row["start_date"], row["end_date"])

    @staticmethod
    def _seed_flight(db_path: str, trip_id: str, user_id: int, dep: str, arr: str) -> None:
        import uuid as _uuid

        from backend.database import db_write
        from backend.utils import now_iso

        with db_write() as conn:
            conn.execute(
                """INSERT INTO flights (
                       id, trip_id, user_id, flight_number,
                       departure_airport, departure_datetime,
                       arrival_airport, arrival_datetime,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(_uuid.uuid4()),
                    trip_id,
                    user_id,
                    "LH722",
                    "FRA",
                    dep,
                    "PEK",
                    arr,
                    now_iso(),
                    now_iso(),
                ),
            )

    def test_segment_extends_the_span_past_the_last_flight(self, test_db):
        from backend.segments.service import SegmentService
        from backend.trips.repository import TripRepository
        from backend.utils import now_iso

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        self._seed_flight(
            test_db,
            trip_id,
            user_id,
            "2026-10-03T20:00:00+00:00",
            "2026-10-03T22:20:00+00:00",
        )
        TripRepository().recompute_span(trip_id, now_iso())
        assert self._span(trip_id) == ("2026-10-03", "2026-10-03")

        # Departs 08:00 Beijing on the 4th, arrives 12:30 on the 4th.
        service.create_segment(trip_id, user_id, segment_payload())

        assert self._span(trip_id) == ("2026-10-03", "2026-10-04")

    def test_span_works_with_segments_and_no_flights(self, test_db):
        """MIN/MAX must be the aggregate forms — the scalar two-argument ones
        return NULL when the flights side is empty, blanking the span."""
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(trip_id, user_id, segment_payload())

        assert self._span(trip_id) == ("2026-10-04", "2026-10-04")

    def test_span_works_with_flights_and_no_segments(self, test_db):
        from backend.trips.repository import TripRepository
        from backend.utils import now_iso

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        self._seed_flight(
            test_db,
            trip_id,
            user_id,
            "2026-10-03T20:00:00+00:00",
            "2026-10-04T06:20:00+00:00",
        )

        TripRepository().recompute_span(trip_id, now_iso())

        assert self._span(trip_id) == ("2026-10-03", "2026-10-04")

    def test_deleting_a_segment_shrinks_the_span_again(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        self._seed_flight(
            test_db,
            trip_id,
            user_id,
            "2026-10-03T20:00:00+00:00",
            "2026-10-03T22:20:00+00:00",
        )
        segment_id = service.create_segment(trip_id, user_id, segment_payload())
        assert self._span(trip_id) == ("2026-10-03", "2026-10-04")

        service.delete_segment(trip_id, segment_id, user_id)

        assert self._span(trip_id) == ("2026-10-03", "2026-10-03")

    def test_editing_a_segments_dates_moves_the_span(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = service.create_segment(trip_id, user_id, segment_payload())

        service.update_segment(
            trip_id,
            segment_id,
            user_id,
            {"departure_datetime": "2026-10-09T08:00", "arrival_datetime": "2026-10-09T12:30"},
        )

        assert self._span(trip_id) == ("2026-10-09", "2026-10-09")

    def test_origin_and_destination_stay_flight_only(self, test_db):
        """They are IATA codes; a station has none to put there."""
        from backend.database import db_conn
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        self._seed_flight(
            test_db,
            trip_id,
            user_id,
            "2026-10-03T20:00:00+00:00",
            "2026-10-03T22:20:00+00:00",
        )
        service.create_segment(trip_id, user_id, segment_payload())

        with db_conn() as conn:
            row = conn.execute(
                "SELECT origin_airport, destination_airport FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        assert row["origin_airport"] == "FRA"
        assert row["destination_airport"] == "PEK"
