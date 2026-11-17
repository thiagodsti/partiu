"""Request/response DTOs for the API keys HTTP API (routes.py)."""

from typing import Literal

from pydantic import BaseModel, Field


class ApiKeyDTO(BaseModel):
    id: int
    name: str
    prefix: str
    scope: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None


class CreateApiKeyDTO(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["read", "write"] = "read"
    # None means the key never expires.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class CreatedApiKeyDTO(ApiKeyDTO):
    # The only response that ever carries the secret.
    key: str
