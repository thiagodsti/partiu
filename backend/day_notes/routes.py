"""
Trip day notes API routes.

  GET    /api/trips/{trip_id}/day-notes         — list all notes for a trip
  PATCH  /api/trips/{trip_id}/day-notes/{date}  — upsert note for a date (YYYY-MM-DD)
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import day_note_service
from .dto import DayNoteDTO, OkDTO, UpsertDayNoteDTO
from .mappers import day_note_to_dto
from .service import InvalidDateError, TripAccessError

router = APIRouter(tags=["day_notes"])


@router.get("/api/trips/{trip_id}/day-notes", response_model=list[DayNoteDTO])
def list_day_notes(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        notes = day_note_service.list_notes(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [day_note_to_dto(n) for n in notes]


@router.patch("/api/trips/{trip_id}/day-notes/{date}", status_code=200, response_model=OkDTO)
def upsert_day_note(
    trip_id: str,
    date: str,
    body: UpsertDayNoteDTO,
    user: dict = Depends(get_current_user),
):
    try:
        day_note_service.upsert_note(trip_id, date, body.content, user["id"])
    except InvalidDateError:
        raise HTTPException(status_code=422, detail="Invalid date format, expected YYYY-MM-DD")
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return OkDTO(ok=True)
