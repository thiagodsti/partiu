"""Tests for recording a place's country and counting it as visited.

The feature this covers: a Stockholm→Oslo train should make Norway a visited
country, which it could not before because the statistic joined `flights` to
`airports.country_code` and a station has no IATA code.
"""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from backend.tests.stays.conftest import seed_trip, seed_user, stay_payload

STOCKHOLM_C = {
    "name": "Stockholm Centralstation",
    "lat": 59.3300,
    "lon": 18.0587,
    "country_code": "SE",
}
OSLO_S = {"name": "Oslo Sentralstasjon", "lat": 59.9107, "lon": 10.7522, "country_code": "NO"}


def _past(hours_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


def _stay(db_path: str, trip_id: str, user_id: int, check_in: str, check_out: str) -> str:
    """A completed stay with explicit local dates, inserted below the service so
    the test controls the dates independently of "now"."""
    from backend.stays.repository import StayRepository

    stay_id = str(uuid.uuid4())
    StayRepository().create(
        stay_id,
        trip_id,
        user_id,
        {
            "kind": "hotel",
            "name": "Test Hotel",
            "address": None,
            "lat": None,
            "lon": None,
            "timezone": None,
            "country": "SE",
            "check_in_datetime": _past(200),
            "check_in_date": check_in,
            "check_out_datetime": _past(100),
            "check_out_date": check_out,
        },
    )
    return stay_id


def _train(db_path: str, trip_id: str, user_id: int, **overrides) -> str:
    """Insert a completed Stockholm→Oslo train directly, bypassing the service
    so the test controls the timestamps relative to 'now'."""
    from backend.segments.repository import SegmentRepository

    values = {
        "type": "train",
        "operator": "SJ",
        "number": "605",
        "booking_reference": None,
        "departure_place": STOCKHOLM_C["name"],
        "departure_lat": STOCKHOLM_C["lat"],
        "departure_lon": STOCKHOLM_C["lon"],
        "departure_datetime": _past(30),
        "departure_timezone": "Europe/Stockholm",
        "departure_country": "SE",
        "arrival_place": OSLO_S["name"],
        "arrival_lat": OSLO_S["lat"],
        "arrival_lon": OSLO_S["lon"],
        "arrival_datetime": _past(24),
        "arrival_timezone": "Europe/Oslo",
        "arrival_country": "NO",
        "seat": None,
        "notes": None,
    }
    values.update(overrides)
    segment_id = str(uuid.uuid4())
    SegmentRepository().create(segment_id, trip_id, user_id, values)
    return segment_id


class TestRecordingTheCountry:
    def test_segment_stores_the_picked_country(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(
            trip_id,
            user_id,
            {
                "type": "train",
                "departure": dict(STOCKHOLM_C),
                "arrival": dict(OSLO_S),
                "departure_datetime": "2026-10-04T08:00",
                "arrival_datetime": "2026-10-04T14:00",
            },
        )

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure.country_code == "SE"
        assert segment.arrival.country_code == "NO"

    def test_country_is_uppercased_and_blank_becomes_none(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(
            trip_id,
            user_id,
            {
                "type": "train",
                "departure": {**STOCKHOLM_C, "country_code": "se"},
                "arrival": {**OSLO_S, "country_code": "  "},
                "departure_datetime": "2026-10-04T08:00",
                "arrival_datetime": "2026-10-04T14:00",
            },
        )

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure.country_code == "SE"
        assert segment.arrival.country_code is None

    def test_country_is_never_derived_from_coordinates(self, test_db):
        """A place with real coordinates but no picked country stays unknown.

        This is the whole design rule: inferring from coordinates was measured
        and put Malmö Central in Denmark, so an unrecorded country is left as
        None rather than guessed.
        """
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)

        service.create_segment(
            trip_id,
            user_id,
            {
                "type": "train",
                "departure": {k: v for k, v in STOCKHOLM_C.items() if k != "country_code"},
                "arrival": {k: v for k, v in OSLO_S.items() if k != "country_code"},
                "departure_datetime": "2026-10-04T08:00",
                "arrival_datetime": "2026-10-04T14:00",
            },
        )

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.departure.lat is not None
        assert segment.departure.country_code is None

    def test_stay_stores_the_picked_country(self, test_db):
        from backend.stays.service import StayService

        service = StayService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        service.create_stay(trip_id, user_id, stay_payload())

        assert service.list_stays(trip_id, user_id)[0].place.country_code == "PT"

    def test_editing_one_field_keeps_the_country(self, test_db):
        from backend.segments.service import SegmentService

        service = SegmentService()
        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        segment_id = service.create_segment(
            trip_id,
            user_id,
            {
                "type": "train",
                "departure": dict(STOCKHOLM_C),
                "arrival": dict(OSLO_S),
                "departure_datetime": "2026-10-04T08:00",
                "arrival_datetime": "2026-10-04T14:00",
            },
        )

        service.update_segment(trip_id, segment_id, user_id, {"seat": "12A"})

        segment = service.list_segments(trip_id, user_id)[0]
        assert segment.arrival.country_code == "NO"


class TestVisitedCountries:
    def test_a_train_to_oslo_counts_norway(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id)

        stats = StatsService().compute_stats(user_id)
        assert set(stats.visited_countries) == {"SE", "NO"}
        assert stats.unique_countries == 2

    def test_ground_travel_adds_no_distance_flights_or_hours(self, test_db):
        """Countries only — a train must not inflate 'hours in air'."""
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id)

        stats = StatsService().compute_stats(user_id)
        assert stats.total_km == 0
        assert stats.total_flights == 0
        assert stats.total_hours == 0.0

    def test_a_stay_counts_its_country(self, test_db):
        from backend.stats.service import StatsService
        from backend.stays.repository import StayRepository

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        StayRepository().create(
            str(uuid.uuid4()),
            trip_id,
            user_id,
            {
                "kind": "hotel",
                "name": "Grand Hotel",
                "address": None,
                "lat": 59.3293,
                "lon": 18.0686,
                "timezone": "Europe/Stockholm",
                "country": "SE",
                "check_in_datetime": _past(72),
                "check_in_date": "2026-01-01",
                "check_out_datetime": _past(48),
                "check_out_date": "2026-01-02",
            },
        )

        stats = StatsService().compute_stats(user_id)
        assert stats.visited_countries == ["SE"]

    def test_future_travel_is_not_counted_yet(self, test_db):
        """Matches the flight rule: only completed travel counts."""
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        _train(test_db, trip_id, user_id, departure_datetime=future, arrival_datetime=future)

        assert StatsService().compute_stats(user_id).visited_countries == []

    def test_places_without_a_country_contribute_nothing(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id, departure_country=None, arrival_country=None)

        assert StatsService().compute_stats(user_id).visited_countries == []

    def test_another_users_trip_does_not_leak_in(self, test_db):
        from backend.stats.service import StatsService

        owner = seed_user(test_db)
        other = seed_user(test_db)
        trip_id = seed_trip(test_db, owner)
        _train(test_db, trip_id, owner)

        assert StatsService().compute_stats(other).visited_countries == []

    def test_the_year_filter_applies(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id)

        this_year = datetime.now(UTC).year
        assert StatsService().compute_stats(user_id, this_year).visited_countries == ["NO", "SE"]
        assert StatsService().compute_stats(user_id, 1999).visited_countries == []


class TestBackfill:
    def test_resolves_missing_countries_through_the_geocoder(self, test_db):
        from backend.stays.country_backfill import backfill_place_countries

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id, departure_country=None, arrival_country=None)

        with (
            patch("backend.stays.country_backfill.photon.is_configured", return_value=True),
            patch(
                "backend.stays.country_backfill.photon.reverse_country",
                # Longitude separates the two cleanly (Stockholm 18.06E, Oslo 10.75E);
                # latitude does not — they are within 0.6 degrees.
                side_effect=lambda lat, lon: "SE" if lon > 15 else "NO",
            ),
            patch("backend.stays.country_backfill._DELAY_SECONDS", 0),
        ):
            written = backfill_place_countries()

        assert written == 2
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT departure_country, arrival_country FROM trip_segments"
        ).fetchone()
        conn.close()
        assert row["departure_country"] == "SE"
        assert row["arrival_country"] == "NO"

    def test_does_nothing_without_a_geocoder(self, test_db):
        """Photon is optional; with none configured the column stays NULL and
        the place simply does not contribute a country."""
        from backend.stays.country_backfill import backfill_place_countries

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id, departure_country=None, arrival_country=None)

        with patch("backend.stays.country_backfill.photon.is_configured", return_value=False):
            assert backfill_place_countries() == 0

    def test_a_partial_sweep_is_retried_on_the_next_run(self, test_db):
        """The done-flag is only set when nothing was left behind — an instance
        whose geocoder was down mid-sweep must pick the rest up later."""
        from backend.database import get_global_setting
        from backend.stays.country_backfill import backfill_place_countries

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id, departure_country=None, arrival_country=None)

        with (
            patch("backend.stays.country_backfill.photon.is_configured", return_value=True),
            patch(
                "backend.stays.country_backfill.photon.reverse_country",
                side_effect=["SE", None],
            ),
            patch("backend.stays.country_backfill._DELAY_SECONDS", 0),
        ):
            backfill_place_countries()

        assert get_global_setting("place_country_backfill_done") != "1"

    def test_places_without_coordinates_are_skipped(self, test_db):
        from backend.stays.country_backfill import backfill_place_countries

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(
            test_db,
            trip_id,
            user_id,
            departure_country=None,
            arrival_country=None,
            departure_lat=None,
            departure_lon=None,
            arrival_lat=None,
            arrival_lon=None,
        )

        with (
            patch("backend.stays.country_backfill.photon.is_configured", return_value=True),
            patch("backend.stays.country_backfill.photon.reverse_country") as reverse,
        ):
            backfill_place_countries()

        reverse.assert_not_called()


class TestGroundCounts:
    """`ground_legs` and `nights_away` — exact counts, unlike ground distance,
    which is deliberately absent."""

    def test_completed_ground_legs_are_counted(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id)
        _train(test_db, trip_id, user_id)

        assert StatsService().compute_stats(user_id).ground_legs == 2

    def test_future_legs_are_not_counted(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        _train(test_db, trip_id, user_id, departure_datetime=future, arrival_datetime=future)

        assert StatsService().compute_stats(user_id).ground_legs == 0

    def test_nights_away_counts_the_nights_of_a_stay(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _stay(test_db, trip_id, user_id, "2026-01-01", "2026-01-05")

        # 1st through 4th; you leave on the 5th, so that is not a night.
        assert StatsService().compute_stats(user_id).nights_away == 4

    def test_overlapping_stays_are_not_double_counted(self, test_db):
        """Two rooms on one night, or a hotel held over a night also spent in an
        apartment, is still one night away."""
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _stay(test_db, trip_id, user_id, "2026-01-01", "2026-01-05")
        _stay(test_db, trip_id, user_id, "2026-01-03", "2026-01-07")

        # Union is the 1st through the 6th, not 4 + 4.
        assert StatsService().compute_stats(user_id).nights_away == 6

    def test_a_day_use_booking_is_no_nights(self, test_db):
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _stay(test_db, trip_id, user_id, "2026-01-01", "2026-01-01")

        assert StatsService().compute_stats(user_id).nights_away == 0

    def test_another_users_stays_do_not_leak_in(self, test_db):
        from backend.stats.service import StatsService

        owner = seed_user(test_db)
        other = seed_user(test_db)
        trip_id = seed_trip(test_db, owner)
        _stay(test_db, trip_id, owner, "2026-01-01", "2026-01-05")

        assert StatsService().compute_stats(other).nights_away == 0

    def test_there_is_no_ground_distance(self, test_db):
        """Rail track runs well above the great-circle line, so ground travel
        contributes no kilometres at all rather than an estimate."""
        from backend.stats.service import StatsService

        user_id = seed_user(test_db)
        trip_id = seed_trip(test_db, user_id)
        _train(test_db, trip_id, user_id)

        stats = StatsService().compute_stats(user_id)
        assert stats.ground_legs == 1
        assert stats.total_km == 0
        assert not hasattr(stats, "ground_km")
