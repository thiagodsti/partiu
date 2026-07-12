"""Request/response DTOs for the user-management HTTP API (routes.py)."""

from pydantic import BaseModel


class UserDTO(BaseModel):
    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None
    totp_enabled: bool
    created_at: str


class CreateUserRequestDTO(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    smtp_recipient_address: str | None = None


class CreateUserResponseDTO(BaseModel):
    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None


class UpdateUserRequestDTO(BaseModel):
    is_admin: bool | None = None
    smtp_recipient_address: str | None = None
    new_password: str | None = None


class OkDTO(BaseModel):
    ok: bool
