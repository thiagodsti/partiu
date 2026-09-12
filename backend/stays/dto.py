"""Request/response DTOs for the trip-stays HTTP API (routes.py)."""

from pydantic import BaseModel, Field


class StayPlaceDTO(BaseModel):
    name: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    timezone: str | None = None
    country_code: str | None = None


class StayPlaceInputDTO(BaseModel):
    """A place as submitted by the client.

    ``lat``/``lon`` are absent until the accommodation picker lands; a stay
    typed by hand has no coordinates and is stored without them. The timezone
    is never supplied by the client — the service derives it from the
    coordinates, exactly as it does for a segment's station.
    """

    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    # ISO-3166-1 alpha-2, straight from the geocoder result the user picked.
    # Never inferred from the coordinates — see photon.reverse_country.
    country_code: str | None = Field(default=None, max_length=2)


class StayDTO(BaseModel):
    id: str
    trip_id: str
    kind: str
    place: StayPlaceDTO
    check_in_datetime: str
    check_in_date: str
    check_out_datetime: str
    check_out_date: str
    nights: int | None
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


class CreateStayDTO(BaseModel):
    kind: str
    place: StayPlaceInputDTO
    # Naive local time at the property, e.g. "2026-10-04T15:00". The service
    # converts to UTC using the property's own timezone and records the local
    # calendar date alongside it.
    check_in_datetime: str
    check_out_datetime: str
    booking_reference: str | None = Field(default=None, max_length=50)
    confirmation: str | None = Field(default=None, max_length=100)
    contact: str | None = Field(default=None, max_length=200)
    room_type: str | None = Field(default=None, max_length=100)
    guests: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=10_000)


class UpdateStayDTO(BaseModel):
    kind: str | None = None
    place: StayPlaceInputDTO | None = None
    check_in_datetime: str | None = None
    check_out_datetime: str | None = None
    booking_reference: str | None = Field(default=None, max_length=50)
    confirmation: str | None = Field(default=None, max_length=100)
    contact: str | None = Field(default=None, max_length=200)
    room_type: str | None = Field(default=None, max_length=100)
    guests: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=10_000)


class CreateStayResponseDTO(BaseModel):
    id: str
    ok: bool


class OkDTO(BaseModel):
    ok: bool


class PlaceSearchResultDTO(BaseModel):
    """One accommodation-or-address candidate from `GET /api/places/search`."""

    name: str
    city: str
    address: str
    country: str
    countrycode: str
    category: str
    lat: float
    lon: float
