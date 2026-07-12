"""
Boarding passes API routes.

  GET    /api/trips/{trip_id}/boarding-passes            — list all for a trip
  GET    /api/flights/{flight_id}/boarding-passes        — list all for a flight
  POST   /api/flights/{flight_id}/boarding-passes        — manual upload
  GET    /api/boarding-passes/{bp_id}/image              — serve image file
  DELETE /api/boarding-passes/{bp_id}                    — delete
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..auth import get_current_user
from . import boarding_pass_service
from .dto import BoardingPassDTO, TripBoardingPassDTO, UploadResponseDTO
from .errors import (
    AccessDeniedError,
    BoardingPassNotFoundError,
    FileTooLargeError,
    FileTooSmallError,
    FlightAccessError,
    ImageNotFoundError,
    TripAccessError,
    UnsupportedFileTypeError,
)
from .mappers import boarding_pass_to_dto, trip_boarding_pass_to_dto

router = APIRouter(tags=["boarding-passes"])


@router.get("/api/trips/{trip_id}/boarding-passes", response_model=list[TripBoardingPassDTO])
def list_trip_boarding_passes(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        items = boarding_pass_service.list_for_trip(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [trip_boarding_pass_to_dto(item) for item in items]


@router.get("/api/flights/{flight_id}/boarding-passes", response_model=list[BoardingPassDTO])
def list_boarding_passes(flight_id: str, user: dict = Depends(get_current_user)):
    try:
        items = boarding_pass_service.list_for_flight(flight_id, user["id"])
    except FlightAccessError:
        raise HTTPException(status_code=404, detail="Flight not found")
    return [boarding_pass_to_dto(item) for item in items]


@router.post(
    "/api/flights/{flight_id}/boarding-passes", status_code=201, response_model=UploadResponseDTO
)
async def upload_boarding_pass(
    flight_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
):
    try:
        boarding_pass_service.check_upload_allowed(flight_id, user["id"], file.content_type)
    except FlightAccessError:
        raise HTTPException(status_code=404, detail="Flight not found")
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    image_bytes = await file.read()
    try:
        bp_id = boarding_pass_service.save_upload(flight_id, image_bytes)
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except FileTooSmallError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return UploadResponseDTO(id=bp_id)


@router.get("/api/boarding-passes/{bp_id}/image")
def get_boarding_pass_image(bp_id: str, user: dict = Depends(get_current_user)):
    try:
        image_path = boarding_pass_service.get_image_path(bp_id, user["id"])
    except BoardingPassNotFoundError:
        raise HTTPException(status_code=404, detail="Boarding pass not found")
    except ImageNotFoundError:
        raise HTTPException(status_code=404, detail="Image file not found")
    except AccessDeniedError:
        raise HTTPException(status_code=403, detail="Access denied")

    suffix = image_path.suffix.lower()
    media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return FileResponse(str(image_path), media_type=media_type)


@router.delete("/api/boarding-passes/{bp_id}", status_code=204)
def delete_boarding_pass(bp_id: str, user: dict = Depends(get_current_user)):
    try:
        boarding_pass_service.delete(bp_id, user["id"])
    except BoardingPassNotFoundError:
        raise HTTPException(status_code=404, detail="Boarding pass not found")
    return None
