"""Shared seed helpers and payload builders for the stays test suite."""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime

_user_counter = itertools.count(1)

# Real coordinates, so the timezone conversions under test are the ones that
# actually run. Honolulu is the case the denormalised local dates exist for:
# at UTC-10, a 15:00 check-in is 01:00Z the *following* day, so a span or a
# planner band derived from DATE(check_in_datetime) lands on the wrong day.
HOTEL_LISBON = {
    "name": "Hotel Avenida Palace",
    "address": "R. 1º de Dezembro 123, 1200-359 Lisboa",
    "lat": 38.7145,
    "lon": -9.1409,
    "country_code": "PT",
}
HOTEL_HONOLULU = {
    "name": "Waikiki Beach Hotel",
    "lat": 21.2793,
    "lon": -157.8292,
    "country_code": "US",
}
HOTEL_TOKYO = {
    "name": "Shinjuku Granbell",
    "lat": 35.6938,
    "lon": 139.7036,
    "country_code": "JP",
}


def seed_user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"staytestuser{next(_user_counter)}"
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


def stay_payload(**overrides) -> dict:
    """A valid create payload: four nights in Lisbon, 15:00 check-in."""
    payload = {
        "kind": "hotel",
        "place": dict(HOTEL_LISBON),
        "check_in_datetime": "2026-10-04T15:00",
        "check_out_datetime": "2026-10-08T11:00",
        "booking_reference": "BK12345",
        "guests": 2,
    }
    payload.update(overrides)
    return payload


def row_values(**overrides) -> dict:
    """A repository-level values dict (already UTC, as the service would emit)."""
    values = {
        "kind": "hotel",
        "name": HOTEL_LISBON["name"],
        "address": HOTEL_LISBON["address"],
        "lat": HOTEL_LISBON["lat"],
        "lon": HOTEL_LISBON["lon"],
        "timezone": "Europe/Lisbon",
        "country": "PT",
        "check_in_datetime": "2026-10-04T14:00:00+00:00",
        "check_in_date": "2026-10-04",
        "check_out_datetime": "2026-10-08T10:00:00+00:00",
        "check_out_date": "2026-10-08",
        "booking_reference": "BK12345",
        "confirmation": None,
        "contact": None,
        "room_type": None,
        "guests": 2,
        "notes": None,
    }
    values.update(overrides)
    return values
