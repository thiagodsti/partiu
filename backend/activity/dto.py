"""Response DTOs for the activity-log HTTP API."""

from pydantic import BaseModel


class ActivityEntryDTO(BaseModel):
    id: int
    action: str
    entity_type: str | None
    entity_id: str | None
    label: str | None
    details: dict
    created_at: str
