"""Shared seed helpers and payload builders for the car-rental test suite."""

import itertools
import sqlite3
import uuid
from datetime import UTC, datetime

_user_counter = itertools.count(1)

# Real coordinates, so the timezone conversions under test are the ones that
# actually run. The Honolulu counter is the case the denormalised local dates
# exist for: at UTC-10, a 09:00 pickup is 19:00Z the *same* day but an 18:00
# drop-off is 04:00Z the *next* one, so a span derived from
# DATE(dropoff_datetime) lands a day late.
COUNTER_VIENNA = {
    "name": "Vienna Airport",
    "address": "Schwechat Airport, Vienna",
    "lat": 48.1103,
    "lon": 16.5697,
    "country_code": "AT",
}
COUNTER_MUNICH = {
    "name": "Munich Airport",
    "lat": 48.3538,
    "lon": 11.7861,
    "country_code": "DE",
}
COUNTER_HONOLULU = {
    "name": "Honolulu Airport",
    "lat": 21.3245,
    "lon": -157.9251,
    "country_code": "US",
}


def seed_user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"rentaltestuser{next(_user_counter)}"
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


def rental_payload(**overrides) -> dict:
    """A valid create payload: four days in Vienna, collected and returned at
    the same counter (the Hertz booking's shape)."""
    payload = {
        "vendor": "Hertz",
        "pickup": dict(COUNTER_VIENNA),
        "dropoff": dict(COUNTER_VIENNA),
        "pickup_datetime": "2026-03-29T09:30",
        "dropoff_datetime": "2026-04-01T23:00",
        "booking_reference": "K78806710D9",
        "vehicle": "Fiat 500 or similar",
    }
    payload.update(overrides)
    return payload


def row_values(**overrides) -> dict:
    """A repository-level values dict (already UTC, as the service would emit)."""
    values = {
        "vendor": "Hertz",
        "pickup_place": COUNTER_VIENNA["name"],
        "pickup_address": COUNTER_VIENNA["address"],
        "pickup_lat": COUNTER_VIENNA["lat"],
        "pickup_lon": COUNTER_VIENNA["lon"],
        "pickup_timezone": "Europe/Vienna",
        "pickup_country": "AT",
        "pickup_datetime": "2026-03-29T07:30:00+00:00",
        "pickup_date": "2026-03-29",
        "dropoff_place": COUNTER_VIENNA["name"],
        "dropoff_address": COUNTER_VIENNA["address"],
        "dropoff_lat": COUNTER_VIENNA["lat"],
        "dropoff_lon": COUNTER_VIENNA["lon"],
        "dropoff_timezone": "Europe/Vienna",
        "dropoff_country": "AT",
        "dropoff_datetime": "2026-04-01T21:00:00+00:00",
        "dropoff_date": "2026-04-01",
        "booking_reference": "K78806710D9",
        "vehicle": "Fiat 500 or similar",
        "driver_name": None,
        "notes": None,
    }
    values.update(overrides)
    return values


def fetch(repository, rental_id: str, trip_id: str):
    """`CarRentalRepository.get` returns `CarRental | None`; tests that have just
    created the row want the object. Asserting here keeps the type checker happy
    and turns a missing row into a clear failure rather than an AttributeError."""
    rental = repository.get(rental_id, trip_id)
    assert rental is not None
    return rental
