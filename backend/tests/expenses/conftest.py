"""Shared seed helpers for the expenses/guests test suites."""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
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


def _seed_trip(db_path: str, user_id: int) -> str:
    trip_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO trips (id, user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (trip_id, user_id, "Test Trip", now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


def _seed_guest(db_path: str, owner_id: int, name: str = "Guest") -> int:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO guests (owner_id, name, created_at) VALUES (?, ?, ?)",
        (owner_id, name, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    guest_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return guest_id
