"""
Trip segments API routes — manually-added non-flight transport legs.

  GET    /api/trips/{trip_id}/segments                 — list all segments
  POST   /api/trips/{trip_id}/segments                 — create segment
  PATCH  /api/trips/{trip_id}/segments/{segment_id}    — update segment
  DELETE /api/trips/{trip_id}/segments/{segment_id}    — delete segment
  GET    /api/stations/search                          — station type-ahead (Photon)
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user
from ..integrations.photon import client as photon
from ..limiter import limiter
from .dto import (
    CreateSegmentDTO,
    CreateSegmentResponseDTO,
    OkDTO,
    SegmentDTO,
    StationDTO,
    UpdateSegmentDTO,
)
from .errors import SegmentNotFoundError, TripAccessError
from .mappers import segment_to_dto
from .service import segment_service

router = APIRouter(tags=["segments"])


@router.get("/api/trips/{trip_id}/segments", response_model=list[SegmentDTO])
def list_segments(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        segments = segment_service.list_segments(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    return [segment_to_dto(s) for s in segments]


@router.post(
    "/api/trips/{trip_id}/segments", status_code=201, response_model=CreateSegmentResponseDTO
)
def create_segment(trip_id: str, body: CreateSegmentDTO, user: dict = Depends(get_current_user)):
    try:
        segment_id = segment_service.create_segment(
            trip_id, user["id"], body.model_dump(exclude_unset=True)
        )
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return CreateSegmentResponseDTO(id=segment_id, ok=True)


@router.patch("/api/trips/{trip_id}/segments/{segment_id}", response_model=OkDTO)
def update_segment(
    trip_id: str,
    segment_id: str,
    body: UpdateSegmentDTO,
    user: dict = Depends(get_current_user),
):
    try:
        segment_service.update_segment(
            trip_id, segment_id, user["id"], body.model_dump(exclude_unset=True)
        )
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except SegmentNotFoundError:
        raise HTTPException(status_code=404, detail="Segment not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return OkDTO(ok=True)


@router.delete("/api/trips/{trip_id}/segments/{segment_id}", response_model=OkDTO)
def delete_segment(trip_id: str, segment_id: str, user: dict = Depends(get_current_user)):
    try:
        segment_service.delete_segment(trip_id, segment_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found") from None
    except SegmentNotFoundError:
        raise HTTPException(status_code=404, detail="Segment not found") from None
    return OkDTO(ok=True)


# Rate-limited because every keystroke in the picker can reach this, and each
# request is proxied to a third-party geocoder rather than served locally.
@router.get("/api/stations/search", response_model=list[StationDTO])
@limiter.limit("60/minute")
def search_stations(
    request: Request,
    q: str = "",
    kind: str = "",
    limit: int = 8,
    user: dict = Depends(get_current_user),
):
    """Station type-ahead. Returns [] when the geocoder is disabled or
    unreachable — the client falls back to free-text entry."""
    results = photon.search_stations(q, kind or None, limit)
    return [StationDTO(**r) for r in _without_osm_id(results)]


def _without_osm_id(results: list[dict]) -> list[dict]:
    """The OSM id is useful for debugging the client but is not part of the
    response contract — a station is identified by its coordinates once picked."""
    return [{k: v for k, v in r.items() if k != "osm_id"} for r in results]
