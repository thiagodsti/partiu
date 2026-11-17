"""Domain object for the API keys feature."""

from dataclasses import dataclass


@dataclass
class ApiKey:
    id: int
    user_id: int
    name: str
    prefix: str
    scope: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
