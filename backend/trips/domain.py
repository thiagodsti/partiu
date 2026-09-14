"""Domain objects for the trips feature."""

from dataclasses import dataclass


@dataclass
class Trip:
    """A raw `trips` table row."""

    id: str
    name: str
    booking_refs: list[str]
    start_date: str | None
    end_date: str | None
    # The span the traveller declared. `start_date`/`end_date` above are derived
    # from the trip's contents *unioned with* this pair, so they can grow past it
    # but never collapse inside it.
    planned_start_date: str | None
    planned_end_date: str | None
    origin_airport: str | None
    destination_airport: str | None
    # The user-typed origin, independent of the flight-derived airport pair
    # above. Destinations are a list and live in `trip_destinations`.
    origin_place: str | None
    origin_lat: float | None
    origin_lon: float | None
    origin_country: str | None
    is_auto_generated: bool
    user_id: int | None
    created_at: str
    updated_at: str
    image_fetched_at: str | None
    rating: float | None
    note: str | None


@dataclass
class ImmichAlbumStatus:
    album_id: str | None
    exists: bool


@dataclass
class ImmichAlbumResult:
    album_id: str
    album_url: str
    asset_count: int | None
    already_exists: bool
