"""Request/response DTOs for the trips HTTP API (routes.py).

Field set intentionally mirrors the original route's ``dict(row)`` shape exactly
(including internal columns the frontend doesn't read, like ``user_id``/
``created_at``/``is_auto_generated``) — this refactor preserves the API contract
byte-for-byte rather than trimming it, since trimming is a separate decision.
"""

from pydantic import BaseModel


class TripPlaceDTO(BaseModel):
    """One place a trip goes to, as the traveller picked it."""

    name: str
    lat: float | None = None
    lon: float | None = None
    country_code: str | None = None


class TripListItemDTO(BaseModel):
    id: str
    name: str
    booking_refs: list[str]
    start_date: str | None
    end_date: str | None
    planned_start_date: str | None
    planned_end_date: str | None
    origin_airport: str | None
    destination_airport: str | None
    origin_place: str | None
    origin_lat: float | None
    origin_lon: float | None
    origin_country: str | None
    destinations: list["TripPlaceDTO"]
    is_auto_generated: int
    user_id: int | None
    created_at: str
    updated_at: str
    image_fetched_at: str | None
    rating: float | None
    note: str | None
    is_owner: bool
    owner_username: str | None
    flight_count: int
    segment_count: int
    stay_count: int
    # Distinct ground-transport types on the trip, so the card can name the
    # kind ('2 trains') when there is only one and fall back to a generic
    # label when there are several.
    segment_types: list[str]
    expenses_total: dict[str, float]
    immich_album_id: str | None
    search_index: str


class TripDetailDTO(BaseModel):
    id: str
    name: str
    booking_refs: list[str]
    start_date: str | None
    end_date: str | None
    planned_start_date: str | None
    planned_end_date: str | None
    origin_airport: str | None
    destination_airport: str | None
    origin_place: str | None
    origin_lat: float | None
    origin_lon: float | None
    origin_country: str | None
    destinations: list["TripPlaceDTO"]
    is_auto_generated: int
    user_id: int | None
    created_at: str
    updated_at: str
    image_fetched_at: str | None
    rating: float | None
    note: str | None
    is_owner: bool
    owner_username: str | None
    flights: list[dict]
    expenses_total: dict[str, float]
    immich_album_id: str | None


class TripListResponseDTO(BaseModel):
    trips: list[TripListItemDTO]


class PlaceFieldsDTO(BaseModel):
    """A trip end as the user picked it: a name, optional coordinates, and the
    geocoder's country code. Coordinates are optional because a hand-typed place
    must still save — it simply contributes no country and no map position."""

    name: str = ""
    lat: float | None = None
    lon: float | None = None
    country_code: str | None = None


class TripCreateDTO(BaseModel):
    name: str
    booking_refs: list[str] = []
    # The dates the form asks for are the *declared* span; the stored
    # `start_date`/`end_date` are recomputed from the trip's contents plus these.
    start_date: str = ""
    end_date: str = ""
    origin_airport: str = ""
    destination_airport: str = ""
    origin: PlaceFieldsDTO | None = None
    destinations: list[PlaceFieldsDTO] | None = None


class TripCreateResponseDTO(BaseModel):
    id: str
    name: str


class TripUpdateDTO(BaseModel):
    name: str | None = None
    booking_refs: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    origin_airport: str | None = None
    destination_airport: str | None = None
    origin: PlaceFieldsDTO | None = None
    destinations: list[PlaceFieldsDTO] | None = None


class CitySearchResultDTO(BaseModel):
    """One populated-place candidate from `GET /api/cities/search`."""

    name: str
    city: str
    address: str
    country: str
    countrycode: str
    category: str
    lat: float
    lon: float


class TripIdResponseDTO(BaseModel):
    id: str


class MergeRequestDTO(BaseModel):
    target_trip_id: str


class MergeResponseDTO(BaseModel):
    target_trip_id: str


class OkDTO(BaseModel):
    ok: bool


class RatingRequestDTO(BaseModel):
    rating: float | None


class RatingResponseDTO(BaseModel):
    rating: float | None


class NoteRequestDTO(BaseModel):
    note: str | None


class NoteResponseDTO(BaseModel):
    note: str | None


class ImmichAlbumStatusDTO(BaseModel):
    album_id: str | None
    exists: bool


class ImmichAlbumResponseDTO(BaseModel):
    album_id: str
    album_url: str
    asset_count: int | None
    already_exists: bool
