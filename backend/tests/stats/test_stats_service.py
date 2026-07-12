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
