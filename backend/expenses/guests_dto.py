"""Request/response DTOs for the guests HTTP API (guests_routes.py)."""

from pydantic import BaseModel


class GuestDTO(BaseModel):
    id: int
    name: str
    created_at: str


class CreateGuestDTO(BaseModel):
    name: str


class UpdateGuestDTO(BaseModel):
    name: str


class CreateGuestResponseDTO(BaseModel):
    id: int
    ok: bool


class AddTripGuestDTO(BaseModel):
    """Put an existing guest on a trip. Creating a guest stays `POST /api/guests`
    — the address book and a trip's roster are separate facts, and folding them
    into one call would make "add to this trip" quietly create duplicates."""

    guest_id: int
