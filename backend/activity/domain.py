"""Domain object for the activity log: one thing that happened to a user's data."""

from dataclasses import dataclass


@dataclass
class ActivityEntry:
    id: int
    user_id: int
    action: str
    entity_type: str | None
    entity_id: str | None
    label: str | None
    details: dict
    created_at: str
