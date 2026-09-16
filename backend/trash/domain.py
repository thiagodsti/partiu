"""Domain objects for the trash."""

from dataclasses import dataclass


@dataclass
class TrashItem:
    id: int
    user_id: int
    kind: str  # "trip" | "flight"
    entity_id: str
    label: str
    summary: dict
    deleted_at: str


@dataclass
class RestoreResult:
    kind: str
    entity_id: str
    label: str
    restored: dict[str, int]
    skipped: dict[str, int]
