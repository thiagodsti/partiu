"""
Trip expenses API routes.

  GET    /api/trips/{trip_id}/expenses                        — list all expenses
  POST   /api/trips/{trip_id}/expenses                        — create expense
  PATCH  /api/trips/{trip_id}/expenses/{expense_id}           — update expense
  DELETE /api/trips/{trip_id}/expenses/{expense_id}           — delete expense
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from . import expense_service
from .dto import CreateExpenseDTO, CreateExpenseResponseDTO, ExpenseDTO, OkDTO, UpdateExpenseDTO
from .mappers import expense_to_dto
from .service import ExpenseNotFoundError, TripAccessError

router = APIRouter(tags=["expenses"])


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
            trip_id, user["id"], body.description, body.amount, body.currency
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
