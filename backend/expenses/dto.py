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
    """The budget that applies to the caller on a trip, and what has been spent
    against it.

    `spent` is the combined share of everyone in `members`, not what any of them
    paid out. `uncounted` is per-currency spend outside the budget's currency —
    reported, never converted, because this app has no exchange rates to convert
    with.

    `members` is who the budget belongs to, owner included, so a shared one can
    say whose purse it is. `owner_user_id` / `owner_username` name its creator:
    a member may edit the budget, and the UI says whose it is before offering to
    clear it.
    """

    amount: float | None = None
    currency: str | None = None
    spent: float
    uncounted: dict[str, float]
    owner_user_id: int | None = None
    owner_username: str | None = None
    members: list[ParticipantDTO] = []


class SetBudgetDTO(BaseModel):
    amount: float
    currency: str
    # Omitted entirely, an existing budget keeps the members it has and a new
    # one belongs to its creator alone — so a client that predates sharing
    # cannot silently un-share a budget by saving an amount.
    members: list[ParticipantInputDTO] | None = None
