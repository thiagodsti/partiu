"""Trip organizer API routes.

GET    /api/trips/{trip_id}/plan                    — stops, items and tasks
POST   /api/trips/{trip_id}/plan/stops              — add a city to the route
PATCH  /api/trips/{trip_id}/plan/stops/{id}
DELETE /api/trips/{trip_id}/plan/stops/{id}
POST   /api/trips/{trip_id}/plan/items              — add a plan item (date null = idea)
PATCH  /api/trips/{trip_id}/plan/items/{id}         — edit or move (date, sort_order)
DELETE /api/trips/{trip_id}/plan/items/{id}
POST   /api/trips/{trip_id}/plan/tasks              — add a to-do
PATCH  /api/trips/{trip_id}/plan/tasks/{id}
DELETE /api/trips/{trip_id}/plan/tasks/{id}
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user
from .dto import (
    CreatedDTO,
    CreateItemDTO,
    CreateStopDTO,
    CreateTaskDTO,
    PlanDTO,
    PlanItemDTO,
    PlanStopDTO,
    PlanTaskDTO,
    UpdateItemDTO,
    UpdateStopDTO,
    UpdateTaskDTO,
)
from .service import PlanRowNotFoundError, TripAccessError, planner_service

router = APIRouter(tags=["planner"])
_BASE = "/api/trips/{trip_id}/plan"


def _call(fn: Callable, *args):
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except PlanRowNotFoundError:
        raise HTTPException(status_code=404, detail="Not found")


def _sent(body: BaseModel) -> dict:
    """Only the fields the client sent, so an explicit null clears a field."""
    return body.model_dump(include=body.model_fields_set)


@router.get(_BASE, response_model=PlanDTO)
def get_plan(trip_id: str, user: dict = Depends(get_current_user)):
    stops, items, tasks = _call(planner_service.get_plan, trip_id, user["id"])
    return PlanDTO(
        stops=[PlanStopDTO(**{k: getattr(s, k) for k in PlanStopDTO.model_fields}) for s in stops],
        items=[PlanItemDTO(**{k: getattr(i, k) for k in PlanItemDTO.model_fields}) for i in items],
        tasks=[PlanTaskDTO(**{k: getattr(t, k) for k in PlanTaskDTO.model_fields}) for t in tasks],
    )


@router.post(_BASE + "/stops", status_code=201, response_model=CreatedDTO)
def create_stop(trip_id: str, body: CreateStopDTO, user: dict = Depends(get_current_user)):
    return CreatedDTO(id=_call(planner_service.create_stop, trip_id, user["id"], body.model_dump()))


@router.patch(_BASE + "/stops/{stop_id}", status_code=204)
def update_stop(
    trip_id: str, stop_id: str, body: UpdateStopDTO, user: dict = Depends(get_current_user)
):
    _call(planner_service.update_stop, trip_id, stop_id, user["id"], _sent(body))


@router.delete(_BASE + "/stops/{stop_id}", status_code=204)
def delete_stop(trip_id: str, stop_id: str, user: dict = Depends(get_current_user)):
    _call(planner_service.delete_stop, trip_id, stop_id, user["id"])


@router.post(_BASE + "/items", status_code=201, response_model=CreatedDTO)
def create_item(trip_id: str, body: CreateItemDTO, user: dict = Depends(get_current_user)):
    return CreatedDTO(id=_call(planner_service.create_item, trip_id, user["id"], body.model_dump()))


@router.patch(_BASE + "/items/{item_id}", status_code=204)
def update_item(
    trip_id: str, item_id: str, body: UpdateItemDTO, user: dict = Depends(get_current_user)
):
    _call(planner_service.update_item, trip_id, item_id, user["id"], _sent(body))


@router.delete(_BASE + "/items/{item_id}", status_code=204)
def delete_item(trip_id: str, item_id: str, user: dict = Depends(get_current_user)):
    _call(planner_service.delete_item, trip_id, item_id, user["id"])


@router.post(_BASE + "/tasks", status_code=201, response_model=CreatedDTO)
def create_task(trip_id: str, body: CreateTaskDTO, user: dict = Depends(get_current_user)):
    return CreatedDTO(id=_call(planner_service.create_task, trip_id, user["id"], body.model_dump()))


@router.patch(_BASE + "/tasks/{task_id}", status_code=204)
def update_task(
    trip_id: str, task_id: str, body: UpdateTaskDTO, user: dict = Depends(get_current_user)
):
    _call(planner_service.update_task, trip_id, task_id, user["id"], _sent(body))


@router.delete(_BASE + "/tasks/{task_id}", status_code=204)
def delete_task(trip_id: str, task_id: str, user: dict = Depends(get_current_user)):
    _call(planner_service.delete_task, trip_id, task_id, user["id"])
