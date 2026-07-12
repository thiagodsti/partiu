"""
Guests API routes (a per-user address book of non-account trip participants).

  GET    /api/guests             — list guests owned by the current user
  POST   /api/guests             — create a guest
  PATCH  /api/guests/{guest_id}  — rename a guest
  DELETE /api/guests/{guest_id}  — delete a guest (must be unused in any expense)
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import guest_service
from .errors import GuestInUseError, GuestNotFoundError
from .guests_dto import CreateGuestDTO, CreateGuestResponseDTO, GuestDTO, UpdateGuestDTO
from .guests_mappers import guest_to_dto

router = APIRouter(tags=["guests"])


@router.get("/api/guests", response_model=list[GuestDTO])
def list_guests(user: dict = Depends(get_current_user)):
    return [guest_to_dto(g) for g in guest_service.list_mine(user["id"])]


@router.post("/api/guests", status_code=201, response_model=CreateGuestResponseDTO)
def create_guest(body: CreateGuestDTO, user: dict = Depends(get_current_user)):
    try:
        guest_id = guest_service.create(user["id"], body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CreateGuestResponseDTO(id=guest_id, ok=True)


@router.patch("/api/guests/{guest_id}", response_model=GuestDTO)
def update_guest(guest_id: int, body: UpdateGuestDTO, user: dict = Depends(get_current_user)):
    try:
        guest = guest_service.rename(guest_id, user["id"], body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GuestNotFoundError:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest_to_dto(guest)


@router.delete("/api/guests/{guest_id}", status_code=204)
def delete_guest(guest_id: int, user: dict = Depends(get_current_user)):
    try:
        guest_service.delete(guest_id, user["id"])
    except GuestNotFoundError:
        raise HTTPException(status_code=404, detail="Guest not found")
    except GuestInUseError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "error": "guest_in_use",
                "params": {"name": e.guest_name, "count": e.expense_count},
            },
        )
    return None
