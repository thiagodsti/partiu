"""Tests for backend.stats.service (aggregation logic beyond the pure haversine/co2_kg helpers,
which are covered directly in test_api_stats.py)."""

import itertools
import uuid
from datetime import UTC, datetime, timedelta

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _seed_flight(
    db_path: str,
    user_id: int,
    dep_dt: datetime,
    arr_dt: datetime,
    dep_airport: str,
    arr_airport: str,
    flight_number: str = "LA800",
) -> str:
    import sqlite3

    flight_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO flights (id, user_id, flight_number, departure_airport,
           departure_datetime, arrival_airport, arrival_datetime, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            flight_id,
            user_id,
            flight_number,
            dep_airport,
            dep_dt.isoformat(),
            arr_airport,
            arr_dt.isoformat(),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return flight_id


def _seed_airport(db_path: str, code: str, city: str, country: str, lat: float, lon: float) -> None:
    from backend.database import db_write

    with db_write() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (code, code, city, country, lat, lon),
        )


class TestComputeStatsEmpty:
    def test_returns_zeroed_stats(self, test_db):
        from backend.stats.service import StatsService

        service = StatsService()
        user_id = _seed_user(test_db)

        stats = service.compute_stats(user_id)
        assert stats.total_flights == 0
        assert stats.total_km == 0
        assert stats.visited_countries == []
        assert stats.flights_by_period == []


class TestVisitedCountries:
    def test_first_and_last_always_count(self, test_db):
        from backend.stats.service import StatsService

        _seed_airport(test_db, "GRU", "Sao Paulo", "BR", -23.43, -46.47)
        _seed_airport(test_db, "LHR", "London", "GB", 51.48, -0.46)

        service = StatsService()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(
            test_db, user_id, now - timedelta(days=10), now - timedelta(days=9), "GRU", "LHR"
        )

        stats = service.compute_stats(user_id)
        assert stats.visited_countries == ["BR", "GB"]

    def test_short_layover_middle_stop_not_counted(self, test_db):
        """A same-day connection (< 24h) shouldn't count the connecting country."""
        from backend.stats.service import StatsService

        _seed_airport(test_db, "GRU", "Sao Paulo", "BR", -23.43, -46.47)
        _seed_airport(test_db, "LIS", "Lisbon", "PT", 38.77, -9.13)
        _seed_airport(test_db, "LHR", "London", "GB", 51.48, -0.46)

        service = StatsService()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        # GRU -> LIS, short layover, LIS -> LHR
        _seed_flight(
            test_db,
            user_id,
            now - timedelta(days=10),
            now - timedelta(days=10, hours=-2),
            "GRU",
            "LIS",
        )
        _seed_flight(
            test_db,
            user_id,
            now - timedelta(days=10, hours=-4),
            now - timedelta(days=9),
            "LIS",
            "LHR",
        )

        stats = service.compute_stats(user_id)
        # Only first departure (BR) and final arrival (GB) count — not the short PT layover
        assert stats.visited_countries == ["BR", "GB"]

    def test_long_layover_middle_stop_counted(self, test_db):
        """A >=24h layover in the connecting country should count as visited."""
        from backend.stats.service import StatsService

        _seed_airport(test_db, "GRU", "Sao Paulo", "BR", -23.43, -46.47)
        _seed_airport(test_db, "LIS", "Lisbon", "PT", 38.77, -9.13)
        _seed_airport(test_db, "LHR", "London", "GB", 51.48, -0.46)

        service = StatsService()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(
            test_db,
            user_id,
            now - timedelta(days=10),
            now - timedelta(days=9, hours=12),
            "GRU",
            "LIS",
        )
        _seed_flight(
            test_db,
            user_id,
            now - timedelta(days=8, hours=12),
            now - timedelta(days=7),
            "LIS",
            "LHR",
        )

        stats = service.compute_stats(user_id)
        assert stats.visited_countries == ["BR", "GB", "PT"]


class TestTopRoutes:
    def test_orders_by_frequency(self, test_db):
        from backend.stats.service import StatsService

        service = StatsService()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(
            test_db, user_id, now - timedelta(days=10), now - timedelta(days=9), "GRU", "LHR", "LA1"
        )
        _seed_flight(
            test_db, user_id, now - timedelta(days=8), now - timedelta(days=7), "GRU", "LHR", "LA2"
        )
        _seed_flight(
            test_db, user_id, now - timedelta(days=6), now - timedelta(days=5), "GRU", "SCL", "LA3"
        )

        stats = service.compute_stats(user_id)
        assert stats.top_routes[0].key == "GRU→LHR"
        assert stats.top_routes[0].count == 2


class TestFlightsByPeriod:
    def test_year_view_has_12_months(self, test_db):
        from backend.stats.service import StatsService

        service = StatsService()
        user_id = _seed_user(test_db)
        year = 2021
        _seed_flight(
            test_db,
            user_id,
            datetime(year, 3, 1, tzinfo=UTC),
            datetime(year, 3, 1, tzinfo=UTC),
            "GRU",
            "LHR",
        )

        stats = service.compute_stats(user_id, year=year)
        assert len(stats.flights_by_period) == 12
        assert stats.flights_by_period[2].label == f"{year}-03"
        assert stats.flights_by_period[2].count == 1


class TestDuplicateLegs:
    """A leg recorded twice is a parsing artefact, not a second flight.

    Found on a real account: a SAS confirmation printing "SK4698 | Airbus
    A320neo" had been read as two legs, the second numbered `A320`. It doubled
    the distance and the CO2 — and, worse, the phantom sat *between* the two
    halves of an Oslo connection and broke the adjacency the layover rule
    depends on, so a 1h05 change of planes counted as having visited Norway.
    """

    @staticmethod
    def _row(dep, arr, dep_dt, arr_dt, dep_country, arr_country, number="SK1"):
        from backend.stats.domain import FlightStatsRow

        return FlightStatsRow(
            flight_number=number,
            airline_code="SK",
            airline_name="SAS",
            departure_airport=dep,
            arrival_airport=arr,
            departure_datetime=dep_dt,
            arrival_datetime=arr_dt,
            duration_minutes=60,
            dep_lat=None,
            dep_lon=None,
            dep_city=None,
            dep_country=dep_country,
            arr_lat=None,
            arr_lon=None,
            arr_city=None,
            arr_country=arr_country,
            trip_name="Trip",
        )

    def _stats(self, rows):
        from unittest.mock import MagicMock

        from backend.stats.service import StatsService

        repo = MagicMock()
        repo.list_completed_flights.return_value = rows
        repo.list_years_with_flights.return_value = []
        repo.list_ground_countries.return_value = []
        repo.count_ground_legs.return_value = 0
        repo.list_stay_night_ranges.return_value = []
        return StatsService(repo).compute_stats(1)

    def test_an_identical_leg_is_counted_once(self):
        leg = self._row("LPA", "OSL", "2025-07-12T14:10:00", "2025-07-12T19:45:00", "ES", "NO")
        phantom = self._row(
            "LPA", "OSL", "2025-07-12T14:10:00", "2025-07-12T19:45:00", "ES", "NO", number="A320"
        )

        assert self._stats([leg, phantom]).total_flights == 1

    def test_a_phantom_does_not_turn_a_connection_into_a_country(self):
        """LPA → OSL → ARN with 1h05 in Oslo: Norway is transit, not a visit."""
        out = self._row("LPA", "OSL", "2025-07-12T14:10:00", "2025-07-12T19:45:00", "ES", "NO")
        phantom = self._row(
            "LPA", "OSL", "2025-07-12T14:10:00", "2025-07-12T19:45:00", "ES", "NO", number="A320"
        )
        onward = self._row("OSL", "ARN", "2025-07-12T20:55:00", "2025-07-12T21:50:00", "NO", "SE")

        countries = self._stats([out, phantom, onward]).visited_countries
        assert "NO" not in countries
        assert set(countries) == {"ES", "SE"}

    def test_the_same_route_on_another_day_is_a_second_flight(self):
        """Dedupe must not collapse a route genuinely flown twice."""
        first = self._row("LPA", "OSL", "2025-07-12T14:10:00", "2025-07-12T19:45:00", "ES", "NO")
        again = self._row("LPA", "OSL", "2025-08-12T14:10:00", "2025-08-12T19:45:00", "ES", "NO")

        assert self._stats([first, again]).total_flights == 2


class TestDeletingATripRemovesItsCountries:
    """A country is only ever evidence of the rows behind it.

    Deleting a trip takes its flights with it (`TripRepository.delete_owned`),
    so the country goes too — unless another trip still visits it. Reported as
    "the stats still show a country after I deleted the trip", which was really
    an orphaned flight row rather than a stats bug; this pins the behaviour so
    it stays true.
    """

    @staticmethod
    def _seed(conn, trip_id: str, user_id: int, flight_id: str, dep: str, arr: str):
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, is_auto_generated, user_id, created_at, updated_at)
               VALUES (?, ?, '[]', 0, ?, ?, ?)""",
            (trip_id, trip_id, user_id, "2020-01-01T00:00:00", "2020-01-01T00:00:00"),
        )
        conn.execute(
            """INSERT INTO flights (id, trip_id, user_id, flight_number, departure_airport,
                   arrival_airport, departure_datetime, arrival_datetime, created_at, updated_at)
               VALUES (?, ?, ?, 'XX1', ?, ?, '2020-03-01T08:00:00', '2020-03-01T12:00:00',
                       '2020-01-01T00:00:00', '2020-01-01T00:00:00')""",
            (flight_id, trip_id, user_id, dep, arr),
        )

    def test_the_country_goes_with_the_trip(self, test_db):
        from backend.database import db_write
        from backend.stats.service import StatsService
        from backend.trips.repository import TripRepository

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
                ("deleter", "x", 0, "2020-01-01T00:00:00"),
            )
            for iata, country in (("GRU", "BR"), ("LIS", "PT"), ("ARN", "SE")):
                conn.execute(
                    "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code) VALUES (?,?,?,?)",
                    (iata, iata, iata, country),
                )
            self._seed(conn, "t-pt", 1, "f-pt", "GRU", "LIS")
            self._seed(conn, "t-se", 1, "f-se", "GRU", "ARN")

        service = StatsService()
        assert set(service.compute_stats(1).visited_countries) == {"BR", "PT", "SE"}

        TripRepository().delete_owned("t-pt", 1)

        # Portugal was only ever on that trip; Brazil is still on the other one.
        after = set(service.compute_stats(1).visited_countries)
        assert "PT" not in after
        assert after == {"BR", "SE"}

    def test_a_country_two_trips_visit_survives_deleting_one(self, test_db):
        from backend.database import db_write
        from backend.stats.service import StatsService
        from backend.trips.repository import TripRepository

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
                ("twice", "x", 0, "2020-01-01T00:00:00"),
            )
            for iata, country in (("GRU", "BR"), ("LIS", "PT")):
                conn.execute(
                    "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code) VALUES (?,?,?,?)",
                    (iata, iata, iata, country),
                )
            self._seed(conn, "t-one", 1, "f-one", "GRU", "LIS")
            self._seed(conn, "t-two", 1, "f-two", "GRU", "LIS")

        service = StatsService()
        TripRepository().delete_owned("t-one", 1)

        assert set(service.compute_stats(1).visited_countries) == {"BR", "PT"}
