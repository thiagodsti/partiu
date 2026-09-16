"""
Trip CRUD routes.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from ..auth import get_current_user
from ..integrations.photon import client as photon
from ..limiter import limiter
from . import ical_service, trip_image_service, trip_immich_service, trip_service
from .dto import (
    CitySearchResultDTO,
    ImmichAlbumResponseDTO,
    ImmichAlbumStatusDTO,
    MergeRequestDTO,
    MergeResponseDTO,
    NoteRequestDTO,
    NoteResponseDTO,
    OkDTO,
    RatingRequestDTO,
    RatingResponseDTO,
    TripCreateDTO,
    TripCreateResponseDTO,
    TripDetailDTO,
    TripIdResponseDTO,
    TripListResponseDTO,
    TripUpdateDTO,
)
from .errors import TripError
from .mappers import trip_to_detail_dto, trip_to_list_item_dto

router = APIRouter(prefix="/api/trips", tags=["trips"])

# `/api/cities/search` cannot hang off the prefixed router, so it gets its own —
# the same shape `stays/` uses for `/api/places/search`. It lives here because a
# trip is its only caller.
cities_router = APIRouter(tags=["trips"])


# Rate-limited because every keystroke in the picker reaches it and each request
# is proxied to a public geocoder rather than served locally.
@cities_router.get("/api/cities/search", response_model=list[CitySearchResultDTO])
@limiter.limit("60/minute")
def search_cities(
    request: Request,
    q: str = "",
    limit: int = 8,
    user: dict = Depends(get_current_user),
):
    """Populated-place type-ahead for a trip's origin and destination.

    Filtered to cities, towns and villages: a trip's ends are places, not venues,
    and the narrower filter is also what keeps the result specific enough for the
    destination photo lookup. Returns [] when the geocoder is disabled or
    unreachable — the form falls back to free-text entry, which saves fine and
    simply contributes no country and no photo.
    """
    results = photon.search_places(q, "city", limit)
    return [CitySearchResultDTO(**{k: v for k, v in r.items() if k != "osm_id"}) for r in results]


@router.get("", response_model=TripListResponseDTO)
def list_trips(user: dict = Depends(get_current_user)):
    """Return all trips ordered by start_date (owned + accepted shared)."""
    items = trip_service.list_trips(user["id"])
    dtos = [
        trip_to_list_item_dto(
            item.trip,
            destinations=item.destinations,
            is_owner=item.is_owner,
            owner_username=item.owner_username,
            flight_count=item.flight_count,
            segment_count=item.segment_count,
            stay_count=item.stay_count,
            car_rental_count=item.car_rental_count,
            collaborator_count=item.collaborator_count,
            pending_invite_count=item.pending_invite_count,
            guest_count=item.guest_count,
            segment_types=item.segment_types,
            expenses_total=item.expenses_total,
            budget_amount=item.budget_amount,
            budget_currency=item.budget_currency,
            budget_spent=item.budget_spent,
            immich_album_id=item.immich_album_id,
            search_index=item.search_index,
        )
        for item in items
    ]
    return TripListResponseDTO(trips=dtos)


@router.get("/{trip_id}", response_model=TripDetailDTO)
def get_trip(trip_id: str, user: dict = Depends(get_current_user)):
    """Return a single trip with its flights."""
    try:
        (
            trip,
            is_owner,
            owner_username,
            flights,
            expenses_total,
            immich_album_id,
            destinations,
            people,
        ) = trip_service.get_trip(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return trip_to_detail_dto(
        trip,
        destinations=destinations,
        is_owner=is_owner,
        owner_username=owner_username,
        flights=flights,
        expenses_total=expenses_total,
        immich_album_id=immich_album_id,
        collaborator_count=people.get("accepted", 0),
        pending_invite_count=people.get("pending", 0),
        guest_count=people.get("guests", 0),
    )


@router.get("/{trip_id}/ical")
def export_trip_ical(trip_id: str, user: dict = Depends(get_current_user)):
    """Export a trip as an iCalendar (.ics) file."""
    try:
        content, filename = ical_service.export_ical(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return PlainTextResponse(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _place_columns(body) -> dict:
    """The trip's typed origin, flattened to columns — empty when none was given.
    Destinations are rows, not columns, and are passed separately."""
    place = getattr(body, "origin", None)
    return trip_service.place_columns("origin", place) if place is not None else {}


@router.post("", status_code=201, response_model=TripCreateResponseDTO)
def create_trip(body: TripCreateDTO, user: dict = Depends(get_current_user)):
    """Create a new trip manually."""
    trip_id = trip_service.create_trip(
        user["id"],
        body.name,
        body.booking_refs,
        body.start_date,
        body.end_date,
        body.origin_airport,
        body.destination_airport,
        places=_place_columns(body),
        destinations=body.destinations,
    )
    return TripCreateResponseDTO(id=trip_id, name=body.name)


@router.patch("/{trip_id}", response_model=TripIdResponseDTO)
def update_trip(trip_id: str, body: TripUpdateDTO, user: dict = Depends(get_current_user)):
    """Update trip fields."""
    try:
        trip_service.update_trip(trip_id, user["id"], body.model_dump(exclude_none=True))
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return TripIdResponseDTO(id=trip_id)


@router.delete("/{trip_id}", status_code=204)
def delete_trip(trip_id: str, user: dict = Depends(get_current_user)):
    """Delete a trip along with its flights (and cascaded boarding_passes/trip_documents)."""
    try:
        trip_service.delete_trip(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return None


@router.post("/{trip_id}/merge", response_model=MergeResponseDTO)
def merge_trip(trip_id: str, body: MergeRequestDTO, user: dict = Depends(get_current_user)):
    """Move all flights from source trip into target trip, then delete source trip."""
    try:
        trip_service.merge_trip(trip_id, body.target_trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return MergeResponseDTO(target_trip_id=body.target_trip_id)


@router.post("/{trip_id}/flights/{flight_id}", response_model=OkDTO)
def add_flight_to_trip(trip_id: str, flight_id: str, user: dict = Depends(get_current_user)):
    """Assign a flight to a trip."""
    try:
        trip_service.add_flight_to_trip(trip_id, flight_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return OkDTO(ok=True)


@router.delete("/{trip_id}/flights/{flight_id}", response_model=OkDTO)
def remove_flight_from_trip(trip_id: str, flight_id: str, user: dict = Depends(get_current_user)):
    """Unlink a flight from a trip."""
    trip_service.remove_flight_from_trip(trip_id, flight_id, user["id"])
    return OkDTO(ok=True)


@router.get("/{trip_id}/image")
async def get_trip_image(trip_id: str, user: dict = Depends(get_current_user)):
    """Return the cached destination photo for this trip, fetching it on first request."""
    try:
        image_path = await trip_image_service.get_trip_image_path(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    media_type = "image/webp" if image_path.suffix == ".webp" else "image/jpeg"
    return FileResponse(
        str(image_path),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
    )


@router.get("/{trip_id}/immich-album/status", response_model=ImmichAlbumStatusDTO)
async def check_immich_album(trip_id: str, user: dict = Depends(get_current_user)):
    """Check whether the stored Immich album still exists. Clears the DB entry if it was deleted."""
    try:
        status = await trip_immich_service.check_immich_album(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return ImmichAlbumStatusDTO(album_id=status.album_id, exists=status.exists)


@router.post("/{trip_id}/immich-album", response_model=ImmichAlbumResponseDTO)
async def create_immich_album(trip_id: str, user: dict = Depends(get_current_user)):
    """Create an Immich album with photos from this trip's date range, or return the existing one."""
    try:
        result = await trip_immich_service.create_immich_album(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return ImmichAlbumResponseDTO(
        album_id=result.album_id,
        album_url=result.album_url,
        asset_count=result.asset_count,
        already_exists=result.already_exists,
    )


@router.post("/{trip_id}/image/refresh", response_model=OkDTO)
async def refresh_trip_image(trip_id: str, user: dict = Depends(get_current_user)):
    """Delete the current image and fetch a different random one."""
    try:
        await trip_image_service.refresh_trip_image(trip_id, user["id"])
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return OkDTO(ok=True)


@router.put("/{trip_id}/rating", response_model=RatingResponseDTO)
def set_trip_rating(trip_id: str, body: RatingRequestDTO, user: dict = Depends(get_current_user)):
    """Set or clear the shared trip rating (0.5–5 in steps of 0.5). Accessible to owner and shared users."""
    try:
        trip_service.set_rating(trip_id, user["id"], body.rating)
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return RatingResponseDTO(rating=body.rating)


@router.put("/{trip_id}/note", response_model=NoteResponseDTO)
def set_trip_note(trip_id: str, body: NoteRequestDTO, user: dict = Depends(get_current_user)):
    """Set or clear the shared trip note. Accessible to owner and shared users."""
    try:
        trip_service.set_note(trip_id, user["id"], body.note)
    except TripError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return NoteResponseDTO(note=body.note)
