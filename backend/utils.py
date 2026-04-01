"""
Shared utility functions used across the backend.
"""

import re
from datetime import UTC, datetime
from typing import overload

# IATA/ICAO flight number: 2-char airline code (letter + letter-or-digit), optional dash, 3-5 digits
# Examples: LA3045, FR2878, G3-2108, SK117
# Rejects aircraft type codes like A380 or A830 (only 1 leading letter + short digit sequence)
FLIGHT_NUMBER_RE = re.compile(r"^[A-Z][A-Z0-9]-?\d{3,5}$")


def validate_flight_number(fn: str) -> bool:
    """Return True if fn looks like a valid IATA/ICAO flight number."""
    normalised = fn.upper().replace(" ", "").replace("\xa0", "")
    return bool(FLIGHT_NUMBER_RE.match(normalised))


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
