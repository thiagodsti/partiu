"""Car rental API routes — a hired vehicle held over a span of a trip.

  GET    /api/trips/{trip_id}/car-rentals              — list all rentals
  POST   /api/trips/{trip_id}/car-rentals              — create rental
  PATCH  /api/trips/{trip_id}/car-rentals/{rental_id}  — update rental
  DELETE /api/trips/{trip_id}/car-rentals/{rental_id}  — delete rental

There is no place-search endpoint here: a rental counter is an address or a
settlement, which `GET /api/places/search` (stays) and `GET /api/stations/search`
(segments) already serve. Adding a third wrapper over the same geocoder would be
one more thing to keep in step for no new behaviour.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from .dto import (
    CarRentalDTO,
    CreateCarRentalDTO,
    CreateCarRentalResponseDTO,
    OkDTO,
    UpdateCarRentalDTO,
)
from .errors import CarRentalNotFoundError, TripAccessError
from .mappers import car_rental_to_dto
from .service import car_rental_service

router = APIRouter(tags=["car-rentals"])


@router.get("/api/trips/{trip_id}/car-rentals", response_model=list[CarRentalDTO])
def list_car_rentals(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        rentals = car_rental_service.list_rentals(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    return [car_rental_to_dto(r) for r in rentals]


@router.post(
    "/api/trips/{trip_id}/car-rentals",
    status_code=201,
    response_model=CreateCarRentalResponseDTO,
)
def create_car_rental(
    trip_id: str, body: CreateCarRentalDTO, user: dict = Depends(get_current_user)
):
    try:
        rental_id = car_rental_service.create_rental(
            trip_id, user["id"], body.model_dump(exclude_unset=True)
        )
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return CreateCarRentalResponseDTO(id=rental_id, ok=True)


@router.patch("/api/trips/{trip_id}/car-rentals/{rental_id}", response_model=OkDTO)
def update_car_rental(
    trip_id: str,
    rental_id: str,
    body: UpdateCarRentalDTO,
    user: dict = Depends(get_current_user),
):
    try:
        car_rental_service.update_rental(
            trip_id, rental_id, user["id"], body.model_dump(exclude_unset=True)
        )
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except CarRentalNotFoundError:
        raise HTTPException(status_code=404, detail="Car rental not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return OkDTO(ok=True)


@router.delete("/api/trips/{trip_id}/car-rentals/{rental_id}", response_model=OkDTO)
def delete_car_rental(trip_id: str, rental_id: str, user: dict = Depends(get_current_user)):
    try:
        car_rental_service.delete_rental(trip_id, rental_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except CarRentalNotFoundError:
        raise HTTPException(status_code=404, detail="Car rental not found") from None
    return OkDTO(ok=True)
