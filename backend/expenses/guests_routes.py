"""
Guests API routes (a per-user address book of non-account trip participants).

  GET    /api/guests             — list guests owned by the current user
  POST   /api/guests             — create a guest
  PATCH  /api/guests/{guest_id}  — rename a guest
  DELETE /api/guests/{guest_id}  — delete a guest (must be unused in any expense)

  GET    /api/trips/{trip_id}/guests             — the guests on one trip
  POST   /api/trips/{trip_id}/guests             — put one of your guests on it
  DELETE /api/trips/{trip_id}/guests/{guest_id}  — take them off (must be unused
                                                   by that trip's expenses)

The trip roster is separate from the address book on purpose: who is travelling
with you on *this* trip is a fact about the trip, not about your contacts.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import guest_service
from .errors import GuestInUseError, GuestNotFoundError, GuestOnTripError, TripAccessError
from .guests_dto import (
    AddTripGuestDTO,
    CreateGuestDTO,
    CreateGuestResponseDTO,
    GuestDTO,
    UpdateGuestDTO,
)
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


@router.get("/api/trips/{trip_id}/guests", response_model=list[GuestDTO])
def list_trip_guests(trip_id: str, user: dict = Depends(get_current_user)):
    """The guests on this trip. Any collaborator sees them, whoever created them."""
    try:
        guests = guest_service.list_for_trip(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [guest_to_dto(g) for g in guests]


@router.post("/api/trips/{trip_id}/guests", status_code=201, response_model=GuestDTO)
def add_trip_guest(trip_id: str, body: AddTripGuestDTO, user: dict = Depends(get_current_user)):
    try:
        guest = guest_service.add_to_trip(trip_id, body.guest_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except GuestNotFoundError:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest_to_dto(guest)


@router.delete("/api/trips/{trip_id}/guests/{guest_id}", status_code=204)
def remove_trip_guest(trip_id: str, guest_id: int, user: dict = Depends(get_current_user)):
    try:
        guest_service.remove_from_trip(trip_id, guest_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except GuestNotFoundError:
        raise HTTPException(status_code=404, detail="Guest not found")
    except GuestOnTripError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return None
