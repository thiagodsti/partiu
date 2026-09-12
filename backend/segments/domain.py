"""Domain objects + shared constants for the trip-segments feature."""

from dataclasses import dataclass
from typing import Literal

SegmentType = Literal["train", "bus", "ferry", "car"]

# Kept as a plain set (not an enum) to mirror how expenses/domain.py holds
# SUPPORTED_CURRENCIES, and so that adding "stay" later is a one-line change
# here plus an icon in the frontend — the DB column has no CHECK constraint.
SEGMENT_TYPES: frozenset[str] = frozenset({"train", "bus", "ferry", "car"})


@dataclass
class Place:
    """One end of a segment: a free-text label plus optional coordinates.

    Coordinates are optional because a hand-typed station that the geocoder
    could not match must still be storable — it simply gets no map line and no
    timezone conversion.
    """

    name: str
    lat: float | None
    lon: float | None
    timezone: str | None
    # ISO-3166-1 alpha-2, as reported by the geocoder for the picked result.
    # Feeds the visited-countries statistic; None means "unknown", which is
    # counted as nothing rather than guessed at.
    country_code: str | None


@dataclass
class Segment:
    id: str
    trip_id: str
    type: str
    operator: str | None
    number: str | None
    booking_reference: str | None
    departure: Place
    departure_datetime: str
    arrival: Place
    arrival_datetime: str
    seat: str | None
    notes: str | None
    created_by: int | None
    created_by_username: str | None
    created_at: str
    updated_at: str

    @property
    def duration_minutes(self) -> int | None:
        from datetime import datetime

        try:
            dep = datetime.fromisoformat(self.departure_datetime)
            arr = datetime.fromisoformat(self.arrival_datetime)
        except (TypeError, ValueError):
            return None
        return int((arr - dep).total_seconds() // 60)
