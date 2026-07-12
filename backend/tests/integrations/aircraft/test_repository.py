"""Tests for backend.integrations.aircraft.repository (AircraftTypeRepository)."""

import itertools
from datetime import UTC, datetime

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


def _seed_flight(db_path: str, user_id: int, flight_id: str, aircraft_type: str | None) -> None:
    import sqlite3

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
        "arrival_airport, arrival_datetime, aircraft_type, user_id, created_at, updated_at) "
        "VALUES (?, 'LA800', 'GRU', '2025-06-01T10:00:00', 'LHR', '2025-06-01T22:00:00', ?, ?, ?, ?)",
        (flight_id, aircraft_type, user_id, now, now),
    )
    conn.commit()
    conn.close()


class TestGetName:
    def test_returns_none_for_unknown_code(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        assert AircraftTypeRepository().get_name("ZZZZ") is None

    def test_returns_seeded_name(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        repo.seed_if_empty()

        assert repo.get_name("A320") == "Airbus A320"

    def test_case_insensitive(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        repo.seed_if_empty()

        assert repo.get_name("a320") == "Airbus A320"


class TestCache:
    def test_caches_new_entry(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        repo.cache("ZZZZ", "Test Aircraft", "Test Manufacturer")

        assert repo.get_name("ZZZZ") == "Test Aircraft"

    def test_does_not_overwrite_existing(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        repo.cache("ZZZZ", "First Name", "Mfr")
        repo.cache("ZZZZ", "Second Name", "Mfr")

        assert repo.get_name("ZZZZ") == "First Name"


class TestCountAndSeed:
    """init_database() (run by the test_db fixture) already calls seed_if_empty()
    once, so the table never starts truly empty — tests assert relative to that
    baseline rather than a count of zero."""

    def test_count_reflects_seed_data(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        assert AircraftTypeRepository().count() > 50

    def test_seed_if_empty_is_idempotent(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        first_count = repo.count()
        repo.seed_if_empty()

        assert repo.count() == first_count

    def test_seed_if_empty_noop_when_already_populated(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        before = repo.count()
        repo.cache("ZZZZ", "Custom Entry", "Custom")
        repo.seed_if_empty()

        # Seeding was skipped (count() was already > 0) — no rows added beyond ours.
        assert repo.get_name("ZZZZ") == "Custom Entry"
        assert repo.count() == before + 1


class TestNormalizeExistingFlightTypes:
    def test_resolves_spaceless_code_to_name(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        repo.seed_if_empty()
        user_id = _seed_user(test_db)
        _seed_flight(test_db, user_id, "f1", "A320")

        repo.normalize_existing_flight_types()

        import sqlite3

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT aircraft_type FROM flights WHERE id = 'f1'").fetchone()
        conn.close()
        assert row["aircraft_type"] == "Airbus A320"

    def test_leaves_already_resolved_names_alone(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        repo.seed_if_empty()
        user_id = _seed_user(test_db)
        _seed_flight(test_db, user_id, "f1", "Airbus A320")

        repo.normalize_existing_flight_types()

        import sqlite3

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT aircraft_type FROM flights WHERE id = 'f1'").fetchone()
        conn.close()
        assert row["aircraft_type"] == "Airbus A320"

    def test_leaves_unknown_code_alone(self, test_db):
        from backend.integrations.aircraft.repository import AircraftTypeRepository

        repo = AircraftTypeRepository()
        user_id = _seed_user(test_db)
        _seed_flight(test_db, user_id, "f1", "ZZZZ")

        repo.normalize_existing_flight_types()

        import sqlite3

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT aircraft_type FROM flights WHERE id = 'f1'").fetchone()
        conn.close()
        assert row["aircraft_type"] == "ZZZZ"
