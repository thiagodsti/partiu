"""
Trip expenses API routes.

  GET    /api/trips/{trip_id}/expenses                        — list all expenses
  POST   /api/trips/{trip_id}/expenses                        — create expense
  PATCH  /api/trips/{trip_id}/expenses/{expense_id}           — update expense
  DELETE /api/trips/{trip_id}/expenses/{expense_id}           — delete expense
  GET    /api/trips/{trip_id}/expenses/participants           — payer/split-between picker
  GET    /api/trips/{trip_id}/expenses/balances                — net balance per participant/currency
  GET    /api/trips/{trip_id}/budget                          — the budget applying to the caller + its spend
  PUT    /api/trips/{trip_id}/budget                          — set it (amount, currency, who it is shared with)
  DELETE /api/trips/{trip_id}/budget                          — clear it
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import expense_service
from .dto import (
    BalancesDTO,
    BudgetDTO,
    CreateExpenseDTO,
    CreateExpenseResponseDTO,
    ExpenseDTO,
    OkDTO,
    ParticipantDTO,
    ParticipantInputDTO,
    SetBudgetDTO,
    UpdateExpenseDTO,
)
from .errors import ExpenseNotFoundError, TripAccessError
from .mappers import balance_entry_to_dto, expense_to_dto

router = APIRouter(tags=["expenses"])


def _to_tuple(p: ParticipantInputDTO | None) -> tuple[str, int] | None:
    return (p.type, p.id) if p is not None else None


def _list_to_tuples(items: list[ParticipantInputDTO] | None) -> list[tuple[str, int]] | None:
    return [(p.type, p.id) for p in items] if items is not None else None


# IMPORTANT: literal sub-paths (participants, balances) must be registered before
# the /{expense_id} routes to avoid FastAPI matching them as an expense id.


@router.get("/api/trips/{trip_id}/expenses/participants", response_model=list[ParticipantDTO])
def list_participants(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        participants = expense_service.list_participants_for_trip(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [ParticipantDTO(type=p.type, id=p.id, name=p.name) for p in participants]


@router.get("/api/trips/{trip_id}/expenses/balances", response_model=BalancesDTO)
def get_balances(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        balances = expense_service.get_balances(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return BalancesDTO(
        balances={
            currency: [balance_entry_to_dto(e) for e in entries]
            for currency, entries in balances.items()
        }
    )


@router.get("/api/trips/{trip_id}/expenses", response_model=list[ExpenseDTO])
def list_expenses(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        expenses = expense_service.list_expenses(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [expense_to_dto(e) for e in expenses]


@router.post(
    "/api/trips/{trip_id}/expenses", status_code=201, response_model=CreateExpenseResponseDTO
)
def create_expense(trip_id: str, body: CreateExpenseDTO, user: dict = Depends(get_current_user)):
    try:
        expense_id = expense_service.create_expense(
            trip_id,
            user["id"],
            body.description,
            body.amount,
            body.currency,
            paid_by=_to_tuple(body.paid_by),
            participants=_list_to_tuples(body.participants),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return CreateExpenseResponseDTO(id=expense_id, ok=True)


@router.patch("/api/trips/{trip_id}/expenses/{expense_id}", response_model=OkDTO)
def update_expense(
    trip_id: str,
    expense_id: str,
    body: UpdateExpenseDTO,
    user: dict = Depends(get_current_user),
):
    try:
        expense_service.update_expense(
            trip_id,
            expense_id,
            user["id"],
            description=body.description,
            amount=body.amount,
            currency=body.currency,
            paid_by=_to_tuple(body.paid_by),
            participants=_list_to_tuples(body.participants),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except ExpenseNotFoundError:
        raise HTTPException(status_code=404, detail="Expense not found")
    return OkDTO(ok=True)


@router.delete("/api/trips/{trip_id}/expenses/{expense_id}", status_code=204)
def delete_expense(trip_id: str, expense_id: str, user: dict = Depends(get_current_user)):
    try:
        expense_service.delete_expense(trip_id, expense_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except ExpenseNotFoundError:
        raise HTTPException(status_code=404, detail="Expense not found")
    return None


# A budget belongs to the people it names, not to the trip: these read and write
# the one that applies to the *caller* — their own if they have one, otherwise
# one a companion shares with them. A collaborator with neither sets their own
# and never touches anyone else's.
@router.get("/api/trips/{trip_id}/budget", response_model=BudgetDTO)
def get_budget(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        status = expense_service.get_budget(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    budget = status.budget
    return BudgetDTO(
        amount=budget.amount if budget else None,
        currency=budget.currency if budget else None,
        spent=status.spent,
        uncounted=status.uncounted,
        owner_user_id=budget.owner_user_id if budget else None,
        owner_username=budget.owner_username if budget else None,
        members=[
            ParticipantDTO(type=m.type, id=m.id, name=m.name)
            for m in (budget.members if budget else [])
        ],
    )


@router.put("/api/trips/{trip_id}/budget", response_model=OkDTO)
def set_budget(trip_id: str, body: SetBudgetDTO, user: dict = Depends(get_current_user)):
    try:
        expense_service.set_budget(
            trip_id,
            user["id"],
            body.amount,
            body.currency,
            members=_list_to_tuples(body.members),
        )
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OkDTO(ok=True)


@router.delete("/api/trips/{trip_id}/budget", response_model=OkDTO)
def clear_budget(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        expense_service.clear_budget(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return OkDTO(ok=True)
