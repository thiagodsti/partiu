"""scripts/reset_demo.py: the demo's six-hourly wipe-and-reseed.

Loaded by path because scripts/ is not a package. Runs inside the container in
production; here it is pointed at a scratch database and data folder.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "reset_demo.py"
_spec = importlib.util.spec_from_file_location("reset_demo", _PATH)
assert _spec and _spec.loader
reset_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reset_demo)


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE airports (iata TEXT);
        CREATE TABLE global_settings (k TEXT, v TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE trips (id TEXT, user_id INTEGER REFERENCES users(id));
        CREATE TABLE trip_plan_items (id TEXT, trip_id TEXT);
        INSERT INTO airports VALUES ('LIS'), ('OSL');
        INSERT INTO global_settings VALUES ('vapid', 'x');
        INSERT INTO users VALUES (1, 'demo');
        INSERT INTO trips VALUES ('t1', 1);
        INSERT INTO trip_plan_items VALUES ('i1', 't1');
        """
    )
    conn.commit()
    conn.close()


def _count(path: Path, table: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


class TestWipeDatabase:
    def test_clears_everything_but_the_keep_list(self, tmp_path):
        db = tmp_path / "partiu.db"
        _make_db(db)

        cleared, kept = reset_demo.wipe_database(str(db))

        assert (cleared, kept) == (3, 2)
        assert _count(db, "users") == 0
        assert _count(db, "trips") == 0
        # A table no list names is cleared too: that is the point of a KEEP list.
        assert _count(db, "trip_plan_items") == 0
        assert _count(db, "airports") == 2
        assert _count(db, "global_settings") == 1

    def test_keeps_the_schema(self, tmp_path):
        db = tmp_path / "partiu.db"
        _make_db(db)
        reset_demo.wipe_database(str(db))
        conn = sqlite3.connect(db)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert {"users", "trips", "trip_plan_items"} <= names

    def test_reference_data_is_on_the_keep_list(self):
        assert {
            "alembic_version",
            "airports",
            "airport_aliases",
            "aircraft_types",
        } <= reset_demo.KEEP


class TestClearUploads:
    def test_empties_the_upload_folders_and_leaves_the_rest(self, tmp_path):
        (tmp_path / "boarding_passes").mkdir()
        (tmp_path / "boarding_passes" / "pass.png").write_bytes(b"x")
        (tmp_path / "trip_documents" / "t1").mkdir(parents=True)
        (tmp_path / "trip_documents" / "t1" / "doc.pdf").write_bytes(b"x")
        (tmp_path / "trip_images").mkdir()
        (tmp_path / "trip_images" / "cover.webp").write_bytes(b"x")

        reset_demo.clear_uploads(tmp_path)

        assert list((tmp_path / "boarding_passes").iterdir()) == []
        assert list((tmp_path / "trip_documents").iterdir()) == []
        # Not visitor uploads: the cached destination photos stay.
        assert (tmp_path / "trip_images" / "cover.webp").exists()

    def test_missing_folders_are_fine(self, tmp_path):
        reset_demo.clear_uploads(tmp_path)


class TestMain:
    def test_wipes_then_reseeds_against_the_local_server(self, tmp_path, monkeypatch):
        db = tmp_path / "partiu.db"
        _make_db(db)
        monkeypatch.setenv("DB_PATH", str(db))
        monkeypatch.delenv("SEED_BASE_URL", raising=False)
        monkeypatch.delenv("APP_PORT", raising=False)

        with patch.object(reset_demo.subprocess, "run") as run:
            reset_demo.main()

        assert _count(db, "users") == 0
        args = run.call_args.args[0]
        assert args[0] == sys.executable
        assert args[1].endswith("seed_demo.py")
        assert args[2] == "http://localhost:8000"
        assert run.call_args.kwargs["check"] is True

    def test_a_failed_seed_fails_the_run(self, tmp_path, monkeypatch):
        db = tmp_path / "partiu.db"
        _make_db(db)
        monkeypatch.setenv("DB_PATH", str(db))

        with patch.object(
            reset_demo.subprocess,
            "run",
            side_effect=reset_demo.subprocess.CalledProcessError(1, "seed"),
        ):
            try:
                reset_demo.main()
            except reset_demo.subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("a failed seed must fail the reset, so the timer reports it")
