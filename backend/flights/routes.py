"""HTTP layer for flights: thin controllers delegating to FlightService."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..auth import get_current_user
from . import flight_aircraft_service, flight_export_service, flight_service
from .dto import (
    EmailBodyDTO,
    FlightCreateDTO,
    FlightDTO,
    FlightIdResponseDTO,
    FlightListResponseDTO,
    FlightUpdateDTO,
    UngroupResponseDTO,
)
from .errors import FlightError
from .mappers import flight_to_dto

router = APIRouter(prefix="/api/flights", tags=["flights"])


@router.get("/export.csv")
def export_flights_csv(user: dict = Depends(get_current_user)):
    """Download all completed flights as a CSV file."""
    csv_text = flight_export_service.export_csv(user["id"])
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=flights.csv"},
    )


@router.get("", response_model=FlightListResponseDTO)
def list_flights(
    trip_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Return flights, optionally filtered by trip or status."""
    try:
        flights, total = flight_service.list_flights(user["id"], trip_id, status, limit, offset)
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return FlightListResponseDTO(
        flights=[flight_to_dto(f) for f in flights], total=total, limit=limit, offset=offset
    )


@router.get("/{flight_id}", response_model=FlightDTO)
def get_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Return a single flight."""
    try:
        flight = flight_service.get_flight(flight_id, user["id"])
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return flight_to_dto(flight)


@router.get("/{flight_id}/email", response_model=EmailBodyDTO)
def get_flight_email(flight_id: str, user: dict = Depends(get_current_user)):
    """Return the raw email body (HTML + text) stored for this flight."""
    try:
        return flight_service.get_flight_email(flight_id, user["id"])
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.get("/{flight_id}/aircraft")
async def get_flight_aircraft(flight_id: str, user: dict = Depends(get_current_user)):
    """Return cached aircraft info, or fetch from OpenSky if the flight is still active.

    Completed flights are not queried against OpenSky — the background aircraft
    sync job handles lookups while flights are airborne.
    """
    try:
        return await flight_aircraft_service.get_flight_aircraft(flight_id, user["id"])
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.post("", status_code=201, response_model=FlightIdResponseDTO)
def create_flight(
    body: FlightCreateDTO, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)
):
    """Manually create a flight."""
    try:
        flight_id = flight_service.create_flight(user["id"], body.model_dump())
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    from ..integrations.aircraft.sync import fetch_aircraft_for_new_flights

    background_tasks.add_task(fetch_aircraft_for_new_flights, [flight_id])

    return FlightIdResponseDTO(id=flight_id)


@router.patch("/{flight_id}", response_model=FlightIdResponseDTO)
def update_flight(flight_id: str, body: FlightUpdateDTO, user: dict = Depends(get_current_user)):
    """Update flight fields."""
    try:
        flight_service.update_flight(flight_id, user["id"], body.model_dump())
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return FlightIdResponseDTO(id=flight_id)


@router.delete("/{flight_id}", status_code=204)
def delete_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Delete a flight (owner only)."""
    try:
        flight_service.delete_flight(flight_id, user["id"])
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@router.post("/{flight_id}/ungroup", status_code=201, response_model=UngroupResponseDTO)
def ungroup_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Move a flight out of its current trip into a new solo trip."""
    try:
        new_trip_id = flight_service.ungroup_flight(flight_id, user["id"])
    except FlightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return UngroupResponseDTO(trip_id=new_trip_id)
