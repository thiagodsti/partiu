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
    origin_airport: str | None
    destination_airport: str | None
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
