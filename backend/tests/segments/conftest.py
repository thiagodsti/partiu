"""Shared seed helpers and payload builders for the segments test suite."""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime

_user_counter = itertools.count(1)

# Real coordinates from Photon for the two stations the feature was designed
# around, so the timezone conversions under test are the ones that actually run.
BEIJING_WEST = {"name": "Beijing West Railway Station", "lat": 39.8936695, "lon": 116.3151027}
XIAN_NORTH = {"name": "Xi'an North Railway Station", "lat": 34.3775583, "lon": 108.9339348}
# Different timezone (CET) so cross-zone conversion is exercised too.
PARIS_NORD = {"name": "Paris Nord", "lat": 48.8809, "lon": 2.3553}


def seed_user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"segtestuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def seed_trip(db_path: str, user_id: int) -> str:
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


def segment_payload(**overrides) -> dict:
    """A valid create payload: Beijing West -> Xi'an North, 08:00-12:30 local."""
    payload = {
        "type": "train",
        "operator": "China Railway",
        "number": "G87",
        "departure": dict(BEIJING_WEST),
        "arrival": dict(XIAN_NORTH),
        "departure_datetime": "2026-10-04T08:00",
        "arrival_datetime": "2026-10-04T12:30",
        "seat": "Car 3, 12A",
    }
    payload.update(overrides)
    return payload


def row_values(**overrides) -> dict:
    """A repository-level values dict (already UTC, as the service would emit)."""
    values = {
        "type": "train",
        "operator": "China Railway",
        "number": "G87",
        "booking_reference": "ABC123",
        "departure_place": BEIJING_WEST["name"],
        "departure_lat": BEIJING_WEST["lat"],
        "departure_lon": BEIJING_WEST["lon"],
        "departure_datetime": "2026-10-04T00:00:00+00:00",
        "departure_timezone": "Asia/Shanghai",
        "arrival_place": XIAN_NORTH["name"],
        "arrival_lat": XIAN_NORTH["lat"],
        "arrival_lon": XIAN_NORTH["lon"],
        "arrival_datetime": "2026-10-04T04:30:00+00:00",
        "arrival_timezone": "Asia/Shanghai",
        "seat": "Car 3, 12A",
        "notes": None,
    }
    values.update(overrides)
    return values
