"""
Trip packing list API routes.

  GET    /api/trips/{trip_id}/packing                       — list all items
  POST   /api/trips/{trip_id}/packing                       — create item
  PATCH  /api/trips/{trip_id}/packing/{item_id}             — update item (text, checked)
  DELETE /api/trips/{trip_id}/packing/{item_id}             — delete item
  POST   /api/trips/{trip_id}/packing/clear-checked         — bulk-delete checked items
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import packing_service
from .dto import (
    CreateItemResponseDTO,
    CreatePackingItemDTO,
    OkDTO,
    PackingItemDTO,
    UpdatePackingItemDTO,
)
from .mappers import item_to_dto
from .service import PackingItemNotFoundError, TripAccessError

router = APIRouter(tags=["packing"])


@router.get("/api/trips/{trip_id}/packing", response_model=list[PackingItemDTO])
def list_items(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        items = packing_service.list_items(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [item_to_dto(item) for item in items]


@router.post("/api/trips/{trip_id}/packing", status_code=201, response_model=CreateItemResponseDTO)
def create_item(trip_id: str, body: CreatePackingItemDTO, user: dict = Depends(get_current_user)):
    try:
        item_id = packing_service.create_item(trip_id, user["id"], body.text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return CreateItemResponseDTO(id=item_id, ok=True)


@router.patch("/api/trips/{trip_id}/packing/{item_id}", response_model=OkDTO)
def update_item(
    trip_id: str,
    item_id: str,
    body: UpdatePackingItemDTO,
    user: dict = Depends(get_current_user),
):
    try:
        packing_service.update_item(
            trip_id, item_id, user["id"], text=body.text, checked=body.checked
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except PackingItemNotFoundError:
        raise HTTPException(status_code=404, detail="Item not found")
    return OkDTO(ok=True)


@router.delete("/api/trips/{trip_id}/packing/{item_id}", status_code=204)
def delete_item(trip_id: str, item_id: str, user: dict = Depends(get_current_user)):
    try:
        packing_service.delete_item(trip_id, item_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except PackingItemNotFoundError:
        raise HTTPException(status_code=404, detail="Item not found")
    return None


@router.post("/api/trips/{trip_id}/packing/clear-checked", status_code=204)
def clear_checked(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        packing_service.clear_checked(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return None
