"""Request/response DTOs for the car-rental HTTP API (routes.py)."""

from pydantic import BaseModel, Field


class RentalPlaceDTO(BaseModel):
    name: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    timezone: str | None = None
    country_code: str | None = None


class RentalPlaceInputDTO(BaseModel):
    """One end of a rental as submitted by the client.

    ``lat``/``lon`` come from the place picker when the geocoder matched, and are
    absent when the counter was typed by hand. The timezone is never supplied by
    the client — the service derives it from the coordinates, as it does for a
    segment's station and a stay's property.
    """

    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=300)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    # ISO-3166-1 alpha-2, straight from the geocoder result the user picked.
    # Never inferred from the coordinates — see photon.reverse_country.
    country_code: str | None = Field(default=None, max_length=2)


class CarRentalDTO(BaseModel):
    id: str
    trip_id: str
    vendor: str
    pickup: RentalPlaceDTO
    pickup_datetime: str
    pickup_date: str
    dropoff: RentalPlaceDTO
    dropoff_datetime: str
    dropoff_date: str
    days: int | None
    is_one_way: bool
    booking_reference: str | None
    vehicle: str | None
    driver_name: str | None
    notes: str | None
    created_by: int | None
    created_by_username: str | None
    created_at: str
    updated_at: str


class CreateCarRentalDTO(BaseModel):
    vendor: str = Field(min_length=1, max_length=100)
    pickup: RentalPlaceInputDTO
    dropoff: RentalPlaceInputDTO
    # Naive local time at the counter, e.g. "2026-10-04T09:30". The service
    # converts to UTC using that counter's own timezone and records the local
    # calendar date alongside it.
    pickup_datetime: str
    dropoff_datetime: str
    booking_reference: str | None = Field(default=None, max_length=50)
    vehicle: str | None = Field(default=None, max_length=200)
    driver_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)


class UpdateCarRentalDTO(BaseModel):
    vendor: str | None = Field(default=None, min_length=1, max_length=100)
    pickup: RentalPlaceInputDTO | None = None
    dropoff: RentalPlaceInputDTO | None = None
    pickup_datetime: str | None = None
    dropoff_datetime: str | None = None
    booking_reference: str | None = Field(default=None, max_length=50)
    vehicle: str | None = Field(default=None, max_length=200)
    driver_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)


class CreateCarRentalResponseDTO(BaseModel):
    id: str
    ok: bool


class OkDTO(BaseModel):
    ok: bool
