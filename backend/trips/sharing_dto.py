"""Request/response DTOs for the trip-sharing HTTP API (sharing_routes.py)."""

from pydantic import BaseModel


class ShareInviteDTO(BaseModel):
    username: str


class TrustedUserRequestDTO(BaseModel):
    username: str


class InvitationDTO(BaseModel):
    id: int
    trip_id: str
    trip_name: str
    invited_by_username: str
    created_at: str


class TripShareDTO(BaseModel):
    id: int
    user_id: int
    username: str
    status: str
    created_at: str


class TrustedUserDTO(BaseModel):
    user_id: int
    username: str
    created_at: str


class OkDTO(BaseModel):
    ok: bool
