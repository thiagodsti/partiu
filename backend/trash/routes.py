"""Trash API.

GET    /api/trash                 — the caller's deleted trips and flights
POST   /api/trash/{id}/restore    — put one back
DELETE /api/trash/{id}            — delete permanently
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from .dto import RestoreResultDTO, TrashItemDTO
from .errors import TrashError
from .service import trash_service

router = APIRouter(prefix="/api/trash", tags=["trash"])


@router.get("", response_model=list[TrashItemDTO])
def list_trash(user: dict = Depends(get_current_user)):
    return [
        TrashItemDTO(
            id=i.id,
            kind=i.kind,
            entity_id=i.entity_id,
            label=i.label,
            summary=i.summary,
            deleted_at=i.deleted_at,
        )
        for i in trash_service.list_items(user["id"])
    ]


@router.post("/{trash_id}/restore", response_model=RestoreResultDTO)
def restore(trash_id: int, user: dict = Depends(get_current_user)):
    try:
        r = trash_service.restore(trash_id, user["id"])
    except TrashError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from None
    return RestoreResultDTO(
        kind=r.kind, entity_id=r.entity_id, label=r.label, restored=r.restored, skipped=r.skipped
    )


@router.delete("/{trash_id}", status_code=204)
def purge(trash_id: int, user: dict = Depends(get_current_user)):
    try:
        trash_service.purge(trash_id, user["id"])
    except TrashError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from None
    return None
