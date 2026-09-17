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
    created: bool = True
    """False when the name already named one of your guests and that one was
    handed back instead. The form needs to know: a list that appends the
    returned id unconditionally ends up with the same row twice."""

    name: str = ""
    """The stored spelling, which on a reuse is the *existing* guest's — typing
    "jimmy" gets you "Jimmy", and the list must show the name the rest of the
    app calls them."""


class AddTripGuestDTO(BaseModel):
    """Put an existing guest on a trip. Creating a guest stays `POST /api/guests`
    — the address book and a trip's roster are separate facts, and folding them
    into one call would make "add to this trip" quietly create duplicates."""

    guest_id: int
