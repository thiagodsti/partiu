"""Request/response DTOs for the trip-segments HTTP API (routes.py)."""

from pydantic import BaseModel, Field


class PlaceDTO(BaseModel):
    name: str
    lat: float | None = None
    lon: float | None = None
    timezone: str | None = None


class PlaceInputDTO(BaseModel):
    """A place as submitted by the client.

    ``lat``/``lon`` come from the station picker when the geocoder matched, and
    are absent when the user typed the name by hand. The timezone is never
    supplied by the client — the service derives it from the coordinates.
    """

    name: str = Field(min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class SegmentDTO(BaseModel):
    id: str
    trip_id: str
    type: str
    operator: str | None
    number: str | None
    booking_reference: str | None
    departure: PlaceDTO
    departure_datetime: str
    arrival: PlaceDTO
    arrival_datetime: str
    duration_minutes: int | None
    seat: str | None
    notes: str | None
    created_by: int | None
    created_by_username: str | None
    created_at: str
    updated_at: str


class CreateSegmentDTO(BaseModel):
    type: str
    departure: PlaceInputDTO
    arrival: PlaceInputDTO
    # Naive local time at the respective place, e.g. "2026-10-04T08:00".
    # The service converts to UTC using each place's own timezone.
    departure_datetime: str
    arrival_datetime: str
    operator: str | None = Field(default=None, max_length=100)
    number: str | None = Field(default=None, max_length=20)
    booking_reference: str | None = Field(default=None, max_length=50)
    seat: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=10_000)


class UpdateSegmentDTO(BaseModel):
    type: str | None = None
    departure: PlaceInputDTO | None = None
    arrival: PlaceInputDTO | None = None
    departure_datetime: str | None = None
    arrival_datetime: str | None = None
    operator: str | None = Field(default=None, max_length=100)
    number: str | None = Field(default=None, max_length=20)
    booking_reference: str | None = Field(default=None, max_length=50)
    seat: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=10_000)


class CreateSegmentResponseDTO(BaseModel):
    id: str
    ok: bool


class StationDTO(BaseModel):
    name: str
    city: str
    country: str
    countrycode: str
    lat: float
    lon: float


class OkDTO(BaseModel):
    ok: bool
