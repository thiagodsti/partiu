"""
Shared utility functions used across the backend.
"""

from datetime import UTC, datetime
from typing import overload


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


@overload
def dt_to_iso(dt: None) -> None: ...
@overload
def dt_to_iso(dt: datetime) -> str: ...
def dt_to_iso(dt: datetime | None) -> str | None:
    """Convert a datetime (or None) to an ISO 8601 string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def calc_duration_minutes(dep_dt, arr_dt) -> int | None:
    """Return flight duration in minutes, or None if inputs are missing/invalid."""
    if not dep_dt or not arr_dt:
        return None
    delta = arr_dt - dep_dt
    minutes = int(delta.total_seconds() / 60)
    return minutes if minutes > 0 else None


def calc_flight_status(arr_dt) -> str:
    """Return 'completed' if the arrival is in the past, otherwise 'upcoming'."""
    if not arr_dt:
        return "upcoming"
    arr_aware = arr_dt
    if arr_aware.tzinfo is None:
        arr_aware = arr_aware.replace(tzinfo=UTC)
    return "completed" if arr_aware < datetime.now(UTC) else "upcoming"
