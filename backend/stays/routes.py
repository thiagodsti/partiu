"""
Trip stays API routes — accommodation booked for a trip.

  GET    /api/trips/{trip_id}/stays              — list all stays
  POST   /api/trips/{trip_id}/stays              — create stay
  PATCH  /api/trips/{trip_id}/stays/{stay_id}    — update stay
  DELETE /api/trips/{trip_id}/stays/{stay_id}    — delete stay
  GET    /api/places/search                     — accommodation/address type-ahead

`/api/places/search` lives here rather than beside the station search in
`segments/` because a stay is its only caller; both are thin wrappers over
`integrations/photon`, which is where the shared lookup logic actually sits.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user
from ..integrations.photon import client as photon
from ..limiter import limiter
from .dto import (
    CreateStayDTO,
    CreateStayResponseDTO,
    OkDTO,
    PlaceSearchResultDTO,
    StayDTO,
    UpdateStayDTO,
)
from .errors import StayNotFoundError, TripAccessError
from .mappers import stay_to_dto
from .service import stay_service

router = APIRouter(tags=["stays"])


@router.get("/api/trips/{trip_id}/stays", response_model=list[StayDTO])
def list_stays(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        stays = stay_service.list_stays(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    return [stay_to_dto(s) for s in stays]


@router.post("/api/trips/{trip_id}/stays", status_code=201, response_model=CreateStayResponseDTO)
def create_stay(trip_id: str, body: CreateStayDTO, user: dict = Depends(get_current_user)):
    try:
        stay_id = stay_service.create_stay(trip_id, user["id"], body.model_dump(exclude_unset=True))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return CreateStayResponseDTO(id=stay_id, ok=True)


@router.patch("/api/trips/{trip_id}/stays/{stay_id}", response_model=OkDTO)
def update_stay(
    trip_id: str,
    stay_id: str,
    body: UpdateStayDTO,
    user: dict = Depends(get_current_user),
):
    try:
        stay_service.update_stay(trip_id, stay_id, user["id"], body.model_dump(exclude_unset=True))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except StayNotFoundError:
        raise HTTPException(status_code=404, detail="Stay not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return OkDTO(ok=True)


@router.delete("/api/trips/{trip_id}/stays/{stay_id}", response_model=OkDTO)
def delete_stay(trip_id: str, stay_id: str, user: dict = Depends(get_current_user)):
    try:
        stay_service.delete_stay(trip_id, stay_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except StayNotFoundError:
        raise HTTPException(status_code=404, detail="Stay not found") from None
    return OkDTO(ok=True)


# Rate-limited because every keystroke in the picker can reach this, and each
# request is proxied to a third-party geocoder rather than served locally.
@router.get("/api/places/search", response_model=list[PlaceSearchResultDTO])
@limiter.limit("60/minute")
def search_places(
    request: Request,
    q: str = "",
    limit: int = 8,
    user: dict = Depends(get_current_user),
):
    """Accommodation and address type-ahead for the stay picker.

    Returns both categories: hotels are in OSM and searchable by name, but a
    private rental generally is not, so the address is the only handle the guest
    has. Returns [] when the geocoder is disabled or unreachable — the form
    falls back to free-text entry.
    """
    results = photon.search_places(q, "stay", limit)
    return [PlaceSearchResultDTO(**{k: v for k, v in r.items() if k != "osm_id"}) for r in results]
