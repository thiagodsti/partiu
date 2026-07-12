"""Domain objects for admin user management."""

from dataclasses import dataclass


@dataclass
class User:
    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None
    totp_enabled: bool
    created_at: str


@dataclass
class CreatedUser:
    """What POST /api/users returns — a smaller shape than the full listing row."""

    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None
