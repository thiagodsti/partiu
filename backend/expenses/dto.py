"""Request/response DTOs for the trip-expenses HTTP API (routes.py)."""

from typing import Literal

from pydantic import BaseModel


class ParticipantInputDTO(BaseModel):
    type: Literal["user", "guest"]
    id: int


class ParticipantDTO(BaseModel):
    type: Literal["user", "guest"]
    id: int
    name: str


class ExpenseDTO(BaseModel):
    id: str
    trip_id: str
    description: str
    amount: float
    currency: str
    created_by: int | None
    created_by_username: str | None
    paid_by: ParticipantDTO
    participants: list[ParticipantDTO]
    created_at: str
    updated_at: str


class CreateExpenseDTO(BaseModel):
    description: str
    amount: float
    currency: str
    paid_by: ParticipantInputDTO | None = None
    participants: list[ParticipantInputDTO] | None = None


class UpdateExpenseDTO(BaseModel):
    description: str | None = None
    amount: float | None = None
    currency: str | None = None
    paid_by: ParticipantInputDTO | None = None
    participants: list[ParticipantInputDTO] | None = None


class CreateExpenseResponseDTO(BaseModel):
    id: str
    ok: bool


class OkDTO(BaseModel):
    ok: bool


class BalanceEntryDTO(BaseModel):
    type: Literal["user", "guest"]
    id: int
    name: str
    net: float


class BalancesDTO(BaseModel):
    balances: dict[str, list[BalanceEntryDTO]]


class BudgetDTO(BaseModel):
    """The caller's budget for a trip and what they have spent against it.

    `spent` is the caller's own share, not what they paid out. `uncounted` is
    per-currency spend outside the budget's currency — reported, never
    converted, because this app has no exchange rates to convert with.
    """

    amount: float | None = None
    currency: str | None = None
    spent: float
    uncounted: dict[str, float]


class SetBudgetDTO(BaseModel):
    amount: float
    currency: str
