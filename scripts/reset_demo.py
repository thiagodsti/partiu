#!/usr/bin/env python3
"""Wipe the demo's data and reseed it with trips dated relative to today.

Runs **inside** the app container, which already ships this directory, so the
host that schedules it needs nothing but `docker compose`:

    docker compose exec -T app python /app/scripts/reset_demo.py

It used to be a host-side shell script with the wipe inlined as a heredoc and
`/usr/local/bin/docker` hard-coded. That path only exists on the Synology NAS
the demo started on, so the reset silently stopped when the demo moved to a
Debian host. Keeping the logic in the image means the schedule is the only
thing a host has to provide. `scripts/reset_demo.sh` is now a thin wrapper.

Steps: clear every table not in KEEP, remove uploaded files, then run
`seed_demo.py` against the server in this container.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Stated as a KEEP list rather than a wipe list, so a table added by a future
# migration is reset without anyone remembering to come back here. The wipe
# list this replaced was written when trips, flights and documents were the
# whole app: by the time stays, segments, car rentals, expenses, budgets,
# guests, packing items, notifications and the trash existed, it was deleting
# the trip row and orphaning everything hanging off it. Nothing cascaded
# either: SQLite opens every connection with foreign_keys OFF (the app turns
# it on in backend/database.py; this standalone script never did), so those
# rows survived every reset and piled up.
KEEP = frozenset(
    {
        "alembic_version",  # schema version
        "airports",  # reference data, expensive to reseed
        "airport_aliases",
        "aircraft_types",
        "global_settings",  # VAPID keys, backfill flags, admin settings
        "non_flight_domains",  # blocked sender list
    }
)

# Folders under the data directory that hold files uploaded by visitors.
UPLOAD_DIRS = ("boarding_passes", "trip_documents")


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC] {msg}", flush=True)


def wipe_database(db_path: str) -> tuple[int, int]:
    """Clear every table not in KEEP. Returns (cleared, kept)."""
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        wiped = [t for t in tables if t not in KEEP]
        # Order is irrelevant with foreign_keys OFF, and leaving it off is
        # deliberate: switching it on here would make DELETE FROM users fail
        # against the NO ACTION references (flights, trips, segments, stays,
        # car rentals, email_sync_state).
        for table in wiped:
            conn.execute(f'DELETE FROM "{table}"')
        conn.commit()
        # Reclaim the space the orphans left behind. Never fatal: a locked
        # database here must not abort the run before the reseed, or the demo
        # stays empty until the next scheduled reset.
        try:
            conn.execute("VACUUM")
        except sqlite3.Error as e:
            _log(f"VACUUM skipped: {e}")
        return len(wiped), len(tables) - len(wiped)
    finally:
        conn.close()


def clear_uploads(data_dir: Path) -> None:
    """Empty the upload folders, keeping the folders themselves."""
    for name in UPLOAD_DIRS:
        folder = data_dir / name
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)


def reseed(base_url: str) -> None:
    """Run seed_demo.py, which recreates the account through /api/auth/setup."""
    seed = Path(__file__).with_name("seed_demo.py")
    subprocess.run([sys.executable, str(seed), base_url], check=True)


def main() -> None:
    db_path = os.getenv("DB_PATH", "/app/data/partiu.db")
    port = os.getenv("APP_PORT", "8000")
    _log("Starting demo reset...")
    cleared, kept = wipe_database(db_path)
    _log(f"Database wiped ({cleared} tables cleared, {kept} kept).")
    clear_uploads(Path(db_path).parent)
    reseed(os.getenv("SEED_BASE_URL", f"http://localhost:{port}"))
    _log("Reset complete.")


if __name__ == "__main__":
    main()
