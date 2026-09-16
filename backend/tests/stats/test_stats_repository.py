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


class TestDestinationCountries:
    """A trip's typed destinations are evidence of a country visited — often the
    only evidence, on a trip that was driven."""

    @staticmethod
    def _trip(conn, trip_id: str, user_id: int, start: str, end: str) -> None:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, start_date, end_date,
                   is_auto_generated, user_id, created_at, updated_at)
               VALUES (?, ?, '[]', ?, ?, 0, ?, ?, ?)""",
            (trip_id, "Brasil", start, end, user_id, "2020-01-01T00:00:00", "2020-01-01T00:00:00"),
        )

    @staticmethod
    def _destination(conn, trip_id: str, name: str, country: str | None) -> None:
        conn.execute(
            """INSERT INTO trip_destinations (id, trip_id, name, lat, lon, country_code, sort_order, created_at)
               VALUES (?, ?, ?, NULL, NULL, ?, 0, ?)""",
            (f"{trip_id}-{name}", trip_id, name, country, "2020-01-01T00:00:00"),
        )

    def test_a_finished_trip_contributes_its_destinations(self, test_db):
        from backend.database import db_write
        from backend.stats.repository import StatsRepository

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
                ("statsuser", "x", 0, "2020-01-01T00:00:00"),
            )
            self._trip(conn, "t-done", 1, "2020-03-01", "2020-03-10")
            self._destination(conn, "t-done", "São Paulo", "BR")
            self._destination(conn, "t-done", "Lisboa", "PT")

        assert set(StatsRepository().list_ground_countries(1)) == {"BR", "PT"}

    def test_a_trip_still_to_come_contributes_nothing(self, test_db):
        """A country you plan to visit is not a country you have visited."""
        from backend.database import db_write
        from backend.stats.repository import StatsRepository

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
                ("future", "x", 0, "2020-01-01T00:00:00"),
            )
            self._trip(conn, "t-future", 1, "2099-03-01", "2099-03-10")
            self._destination(conn, "t-future", "Tóquio", "JP")

        assert StatsRepository().list_ground_countries(1) == []

    def test_a_hand_typed_destination_has_no_country_to_give(self, test_db):
        from backend.database import db_write
        from backend.stats.repository import StatsRepository

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
                ("typed", "x", 0, "2020-01-01T00:00:00"),
            )
            self._trip(conn, "t-typed", 1, "2020-03-01", "2020-03-10")
            self._destination(conn, "t-typed", "Somewhere", None)

        assert StatsRepository().list_ground_countries(1) == []


class TestCancelledFlightsAreNotStatistics:
    """A cancelled flight is one that did not happen.

    Without this filter it still contributed its distance, its CO2 and both
    airports' countries — and, worse, sat between the two halves of a connection
    and broke the adjacency the 24h layover rule walks, exactly the way the
    duplicate legs `_dedupe` exists to collapse did.
    """

    @staticmethod
    def _set_status(db_path: str, flight_id: str, status) -> None:
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE flights SET status = ? WHERE id = ?", (status, flight_id))
        conn.commit()
        conn.close()

    def test_a_cancelled_flight_is_excluded(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        flown = _seed_flight(
            test_db, user_id, now - timedelta(days=5), now - timedelta(days=5, hours=-2)
        )
        cancelled = _seed_flight(
            test_db,
            user_id,
            now - timedelta(days=4),
            now - timedelta(days=4, hours=-2),
            flight_number="LA999",
        )
        self._set_status(test_db, flown, "completed")
        self._set_status(test_db, cancelled, "cancelled")

        numbers = {r.flight_number for r in repo.list_completed_flights(user_id)}
        assert numbers == {"LA800"}

    def test_a_null_status_is_still_counted(self, test_db):
        """The trap in the filter itself: `status` is nullable and in SQL
        `NULL != 'cancelled'` is NULL, not true. A bare `!=` would drop every
        flight whose status was never written — a filter silently becoming data
        loss."""
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        now = datetime.now(UTC)
        flight_id = _seed_flight(
            test_db, user_id, now - timedelta(days=3), now - timedelta(days=3, hours=-2)
        )
        self._set_status(test_db, flight_id, None)

        assert len(repo.list_completed_flights(user_id)) == 1

    def test_a_year_of_only_cancelled_flights_is_not_offered(self, test_db):
        from backend.stats.repository import StatsRepository

        repo = StatsRepository()
        user_id = _seed_user(test_db)
        cancelled = _seed_flight(
            test_db,
            user_id,
            datetime(2019, 5, 1, 10, tzinfo=UTC),
            datetime(2019, 5, 1, 12, tzinfo=UTC),
        )
        self._set_status(test_db, cancelled, "cancelled")

        assert "2019" not in repo.list_years_with_flights(user_id)
