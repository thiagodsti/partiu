"""Tests for backend.stats.repository (read-only queries over flights/airports/trips)."""

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
    flight_number: str = "LA800",
    dep_airport: str = "GRU",
    arr_airport: str = "LHR",
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


class TestListCompletedFlights:
    def test_excludes_upcoming_flights(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(test_db, user_id, now + timedelta(days=1), now + timedelta(days=2))

        assert repo.list_completed_flights(user_id) == []

    def test_includes_past_flights(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(test_db, user_id, now - timedelta(days=10), now - timedelta(days=9))

        rows = repo.list_completed_flights(user_id)
        assert len(rows) == 1
        assert rows[0].flight_number == "LA800"

    def test_isolates_by_user(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user1 = _seed_user(test_db)
        user2 = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(test_db, user1, now - timedelta(days=10), now - timedelta(days=9))

        assert len(repo.list_completed_flights(user1)) == 1
        assert repo.list_completed_flights(user2) == []

    def test_year_filter(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        _seed_flight(
            test_db,
            user_id,
            datetime(2020, 6, 1, tzinfo=UTC),
            datetime(2020, 6, 1, tzinfo=UTC),
        )

        assert len(repo.list_completed_flights(user_id, year=2020)) == 1
        assert len(repo.list_completed_flights(user_id, year=2021)) == 0

    def test_joins_airport_coordinates(self, test_db):
        from backend.database import db_write
        from backend.stats.repository import StatsRepository

        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("GRU", "Guarulhos", "Sao Paulo", "BR", -23.4356, -46.4731),
            )

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        _seed_flight(test_db, user_id, now - timedelta(days=10), now - timedelta(days=9))

        [row] = repo.list_completed_flights(user_id)
        assert row.dep_lat == -23.4356
        assert row.dep_city == "Sao Paulo"


class TestListYearsWithFlights:
    def test_returns_distinct_years_descending(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        _seed_flight(
            test_db, user_id, datetime(2020, 6, 1, tzinfo=UTC), datetime(2020, 6, 1, tzinfo=UTC)
        )
        _seed_flight(
            test_db, user_id, datetime(2022, 6, 1, tzinfo=UTC), datetime(2022, 6, 1, tzinfo=UTC)
        )

        assert repo.list_years_with_flights(user_id) == ["2022", "2020"]

    def test_empty_for_new_user(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        assert repo.list_years_with_flights(user_id) == []
