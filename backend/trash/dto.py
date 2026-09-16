"""Response DTOs for the trash HTTP API."""

from pydantic import BaseModel


class TrashItemDTO(BaseModel):
    id: int
    kind: str
    entity_id: str
    label: str
    summary: dict
    deleted_at: str


class RestoreResultDTO(BaseModel):
    kind: str
    entity_id: str
    label: str
    restored: dict[str, int]
    skipped: dict[str, int]
