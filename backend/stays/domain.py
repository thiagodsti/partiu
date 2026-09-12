"""Domain objects + shared constants for the trip-stays feature."""

from dataclasses import dataclass
from datetime import date

# Kept as a plain set rather than an enum, mirroring segments' SEGMENT_TYPES —
# the DB column has no CHECK constraint, so adding a kind is a one-line change
# here plus an icon in the frontend.
STAY_KINDS: frozenset[str] = frozenset({"hotel", "airbnb", "hostel", "other"})

# A year-long booking is almost certainly a mistyped year, not a lease.
MAX_NIGHTS = 365


@dataclass
class StayPlace:
    """Where the stay is. One place, unlike a segment's two.

    ``address`` is separate from ``name`` because they serve different readers:
    the name titles the card, the address is what goes into the calendar's
    LOCATION field and makes the entry tappable into a maps app.

    Coordinates are optional for the same reason they are on a segment — an
    Airbnb often has no OSM entry and its street address is only revealed after
    booking, so a hand-typed place must still save. It simply gets no map pin
    and no timezone conversion.
    """

    name: str
    address: str | None
    lat: float | None
    lon: float | None
    timezone: str | None
    # ISO-3166-1 alpha-2, as reported by the geocoder for the picked result.
    # Feeds the visited-countries statistic; None means "unknown", which is
    # counted as nothing rather than guessed at.
    country_code: str | None


@dataclass
class Stay:
    id: str
    trip_id: str
    kind: str
    place: StayPlace
    check_in_datetime: str
    # Local calendar date at the property, denormalised at write time. See the
    # 0024 migration for why this is not derived from the UTC instant on read.
    check_in_date: str
    check_out_datetime: str
    check_out_date: str
    booking_reference: str | None
    confirmation: str | None
    contact: str | None
    room_type: str | None
    guests: int | None
    notes: str | None
    created_by: int | None
    created_by_username: str | None
    created_at: str
    updated_at: str

    @property
    def nights(self) -> int | None:
        """Nights slept, counted on local calendar dates rather than elapsed
        hours — a 15:00 check-in to an 11:00 check-out two days later is two
        nights, though it is only 44 hours."""
        try:
            return (
                date.fromisoformat(self.check_out_date) - date.fromisoformat(self.check_in_date)
            ).days
        except (TypeError, ValueError):
            return None
