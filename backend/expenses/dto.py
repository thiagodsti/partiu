"""Request/response DTOs for the trip-expenses HTTP API (routes.py)."""

from pydantic import BaseModel


class ExpenseDTO(BaseModel):
    id: str
    trip_id: str
    description: str
    amount: float
    currency: str
    created_by: int | None
    created_by_username: str | None
    created_at: str
    updated_at: str


class CreateExpenseDTO(BaseModel):
    description: str
    amount: float
    currency: str


class UpdateExpenseDTO(BaseModel):
    description: str | None = None
    amount: float | None = None
    currency: str | None = None


class CreateExpenseResponseDTO(BaseModel):
    id: str
    ok: bool


class OkDTO(BaseModel):
    ok: bool
