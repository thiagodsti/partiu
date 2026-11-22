"""Request/response DTOs for the trip organizer API."""

from typing import Literal

from pydantic import BaseModel, Field

_DATE = r"^\d{4}-\d{2}-\d{2}$"
_TIME = r"^\d{2}:\d{2}$"


class PlanStopDTO(BaseModel):
    id: str
    name: str
    lat: float | None
    lon: float | None
    country_code: str | None
    start_date: str
    end_date: str
    notes: str | None


class PlanItemDTO(BaseModel):
    id: str
    date: str | None
    time: str | None
    title: str
    notes: str | None
    status: str
    sort_order: int


class PlanTaskDTO(BaseModel):
    id: str
    text: str
    done: bool
    assignee_type: Literal["user", "guest"] | None
    assignee_id: int | None
    sort_order: int


class PlanDTO(BaseModel):
    stops: list[PlanStopDTO]
    items: list[PlanItemDTO]
    tasks: list[PlanTaskDTO]


class CreateStopDTO(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lat: float | None = None
    lon: float | None = None
    country_code: str | None = Field(default=None, max_length=2)
    start_date: str = Field(pattern=_DATE)
    end_date: str = Field(pattern=_DATE)
    notes: str | None = Field(default=None, max_length=2000)


class UpdateStopDTO(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    lat: float | None = None
    lon: float | None = None
    country_code: str | None = Field(default=None, max_length=2)
    start_date: str | None = Field(default=None, pattern=_DATE)
    end_date: str | None = Field(default=None, pattern=_DATE)
    notes: str | None = Field(default=None, max_length=2000)


class CreateItemDTO(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    date: str | None = Field(default=None, pattern=_DATE)
    time: str | None = Field(default=None, pattern=_TIME)
    notes: str | None = Field(default=None, max_length=2000)
    status: str = "idea"


class UpdateItemDTO(BaseModel):
    """Every field is optional; ``date``/``time`` are cleared by sending null
    explicitly, which is why the service reads ``model_fields_set``."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    date: str | None = Field(default=None, pattern=_DATE)
    time: str | None = Field(default=None, pattern=_TIME)
    notes: str | None = Field(default=None, max_length=2000)
    status: str | None = None
    sort_order: int | None = None


class CreateTaskDTO(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    assignee_type: Literal["user", "guest"] | None = None
    assignee_id: int | None = None


class UpdateTaskDTO(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None
    assignee_type: Literal["user", "guest"] | None = None
    assignee_id: int | None = None


class CreatedDTO(BaseModel):
    id: str
