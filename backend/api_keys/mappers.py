"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import ApiKey
from .dto import ApiKeyDTO, CreatedApiKeyDTO


def row_to_key(row: sqlite3.Row) -> ApiKey:
    return ApiKey(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        prefix=row["prefix"],
        scope=row["scope"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        expires_at=row["expires_at"],
    )


def key_to_dto(key: ApiKey) -> ApiKeyDTO:
    return ApiKeyDTO(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scope=key.scope,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    )


def created_key_to_dto(key: ApiKey, secret: str) -> CreatedApiKeyDTO:
    return CreatedApiKeyDTO(**key_to_dto(key).model_dump(), key=secret)
