"""Tests for backend.settings.repository (global_settings, user columns, airport counts)."""

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


class TestGlobalSettings:
    def test_default_when_unset(self, test_db):
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        assert repo.get_global_setting("sync_interval_minutes", "10") == "10"

    def test_set_then_get(self, test_db):
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        repo.set_global_setting("sync_interval_minutes", "30")
        assert repo.get_global_setting("sync_interval_minutes", "10") == "30"


class TestSmtpConflict:
    def test_false_when_no_conflict(self, test_db):
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        user_id = _seed_user(test_db)
        assert repo.has_smtp_conflict("me@example.com", user_id) is False

    def test_true_when_another_user_has_it(self, test_db):
        import sqlite3

        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        other_id = _seed_user(test_db)
        me_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "UPDATE users SET smtp_recipient_address = ? WHERE id = ?",
            ("shared@example.com", other_id),
        )
        conn.commit()
        conn.close()

        assert repo.has_smtp_conflict("shared@example.com", me_id) is True
        # Case-insensitive match
        assert repo.has_smtp_conflict("SHARED@example.com", me_id) is True

    def test_excludes_self(self, test_db):
        import sqlite3

        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "UPDATE users SET smtp_recipient_address = ? WHERE id = ?",
            ("me@example.com", user_id),
        )
        conn.commit()
        conn.close()

        assert repo.has_smtp_conflict("me@example.com", user_id) is False


class TestUpdateUserSettings:
    def test_updates_given_columns(self, test_db):
        import sqlite3

        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        user_id = _seed_user(test_db)
        repo.update_user_settings(user_id, {"gmail_address": "me@gmail.com", "imap_port": 993})

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT gmail_address, imap_port FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        conn.close()
        assert row["gmail_address"] == "me@gmail.com"
        assert row["imap_port"] == 993


class TestNonFlightDomains:
    """The table comes pre-seeded by alembic migration 0010 with the same domains
    hardcoded in sync/pipeline.py, so `test_db` never starts empty — tests assert
    relative to that baseline rather than an empty list."""

    def test_seeded_by_migration(self, test_db):
        from backend.settings.repository import SettingsRepository

        domains = {d["domain"] for d in SettingsRepository().list_non_flight_domains()}
        assert "booking.com" in domains

    def test_add_then_list(self, test_db):
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        repo.add_non_flight_domain("example.com", "test note")

        domains = {d["domain"]: d for d in repo.list_non_flight_domains()}
        assert domains["example.com"]["note"] == "test note"

    def test_add_duplicate_ignored(self, test_db):
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        repo.add_non_flight_domain("example.com")
        before = len(repo.list_non_flight_domains())
        repo.add_non_flight_domain("example.com")

        assert len(repo.list_non_flight_domains()) == before

    def test_remove(self, test_db):
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        repo.add_non_flight_domain("example.com")
        repo.remove_non_flight_domain("example.com")

        domains = {d["domain"] for d in repo.list_non_flight_domains()}
        assert "example.com" not in domains


class TestAirportCount:
    def test_reflects_seeded_rows(self, test_db):
        from backend.database import db_write
        from backend.settings.repository import SettingsRepository

        repo = SettingsRepository()
        assert repo.get_airport_count() == 0

        with db_write() as conn:
            conn.execute(
                "INSERT INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
                " VALUES ('GRU', 'Guarulhos', 'Sao Paulo', 'BR', -23.43, -46.47)"
            )
        assert repo.get_airport_count() == 1
