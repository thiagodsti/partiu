"""Request/response DTOs for the day-notes HTTP API (routes.py)."""

from pydantic import BaseModel


class DayNoteDTO(BaseModel):
    date: str
    content: str
    updated_at: str
    updated_by_username: str | None


class UpsertDayNoteDTO(BaseModel):
    content: str


class OkDTO(BaseModel):
    ok: bool
