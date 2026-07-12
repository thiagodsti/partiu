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
