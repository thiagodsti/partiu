"""Activity log API.

GET /api/activity?limit=100 — the caller's own history, newest first.
"""

from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user
from .dto import ActivityEntryDTO
from .service import activity_service

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityEntryDTO])
def list_activity(limit: int = Query(100, ge=1, le=500), user: dict = Depends(get_current_user)):
    entries = activity_service.list_for_user(user["id"], limit)
    return [
        ActivityEntryDTO(
            id=e.id,
            action=e.action,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            label=e.label,
            details=e.details,
            created_at=e.created_at,
        )
        for e in entries
    ]
