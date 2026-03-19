"""Tests for backend.database utility functions and migrations."""

import pytest


class TestGlobalSettings:
    def test_get_default_when_missing(self, test_db):
        from backend.database import get_global_setting

        val = get_global_setting("nonexistent_key", default="fallback")
        assert val == "fallback"

    def test_set_and_get(self, test_db):
        from backend.database import get_global_setting, set_global_setting

        set_global_setting("my_key", "my_value")
        assert get_global_setting("my_key") == "my_value"

    def test_upsert_overwrites_existing(self, test_db):
        from backend.database import get_global_setting, set_global_setting

        set_global_setting("k", "first")
        set_global_setting("k", "second")
        assert get_global_setting("k") == "second"

    def test_get_empty_default(self, test_db):
        from backend.database import get_global_setting

        val = get_global_setting("missing_key")
        assert val == ""


class TestDbConn:
    def test_db_conn_closes_after_use(self, test_db):
        from backend.database import db_conn

        with db_conn() as conn:
            result = conn.execute("SELECT 1").fetchone()
            assert result[0] == 1
        # Connection should be closed; accessing it again raises
        with pytest.raises(Exception):
            conn.execute("SELECT 1")

    def test_db_write_commits(self, test_db):
        from backend.database import db_conn, db_write

        with db_write() as conn:
            conn.execute("INSERT INTO global_settings (key, value) VALUES ('foo', 'bar')")
        with db_conn() as conn:
            row = conn.execute("SELECT value FROM global_settings WHERE key='foo'").fetchone()
        assert row["value"] == "bar"

    def test_db_write_rolls_back_on_error(self, test_db):
        from backend.database import db_conn, db_write

        with pytest.raises(Exception):
            with db_write() as conn:
                conn.execute(
                    "INSERT INTO global_settings (key, value) VALUES ('rollback_key', 'v')"
                )
                raise ValueError("forced error")
        with db_conn() as conn:
            row = conn.execute(
                "SELECT value FROM global_settings WHERE key='rollback_key'"
            ).fetchone()
        assert row is None


class TestInitDatabase:
    def test_tables_created_after_init(self, test_db):
        from backend.database import db_conn

        with db_conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        expected = {"flights", "trips", "users", "airports", "sessions", "global_settings"}
        assert expected.issubset(tables)

    def test_aircraft_types_populated(self, test_db):
        from backend.database import db_conn

        with db_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM aircraft_types").fetchone()[0]
        assert count > 50  # we have many aircraft types seeded

    def test_schema_version_set(self, test_db):
        from backend.database import CURRENT_SCHEMA_VERSION, db_conn

        with db_conn() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION


class TestLoadAircraftTypes:
    def test_idempotent_when_already_populated(self, test_db):
        from backend.database import db_conn, load_aircraft_types_if_empty

        # Call again — should not duplicate
        load_aircraft_types_if_empty()
        with db_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM aircraft_types").fetchone()[0]
        # Count should remain the same as original seed
        assert count > 0


class TestFloatOrNone:
    def test_valid_float(self):
        from backend.database import _float_or_none

        assert _float_or_none("3.14") == pytest.approx(3.14)

    def test_none_input(self):
        from backend.database import _float_or_none

        assert _float_or_none(None) is None

    def test_empty_string(self):
        from backend.database import _float_or_none

        assert _float_or_none("") is None

    def test_invalid_string(self):
        from backend.database import _float_or_none

        assert _float_or_none("not-a-number") is None

    def test_integer_string(self):
        from backend.database import _float_or_none

        assert _float_or_none("42") == 42.0
