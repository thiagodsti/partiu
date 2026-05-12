"""
Trip expenses API routes.

  GET    /api/trips/{trip_id}/expenses                        — list all expenses
  POST   /api/trips/{trip_id}/expenses                        — create expense
  PATCH  /api/trips/{trip_id}/expenses/{expense_id}           — update expense
  DELETE /api/trips/{trip_id}/expenses/{expense_id}           — delete expense
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import can_access_trip
from ..utils import now_iso

router = APIRouter(tags=["expenses"])

SUPPORTED_CURRENCIES = {
    "AED",
    "ARS",
    "AUD",
    "BRL",
    "CAD",
    "CHF",
    "CLP",
    "CNY",
    "COP",
    "CZK",
    "DKK",
    "EGP",
    "EUR",
    "GBP",
    "HKD",
    "HUF",
    "IDR",
    "ILS",
    "INR",
    "ISK",
    "JPY",
    "KRW",
    "MAD",
    "MXN",
    "MYR",
    "NOK",
    "NZD",
    "PEN",
    "PHP",
    "PLN",
    "QAR",
    "RON",
    "SAR",
    "SEK",
    "SGD",
    "THB",
    "TRY",
    "TWD",
    "UAH",
    "USD",
    "ZAR",
}


@router.get("/api/trips/{trip_id}/expenses")
def list_expenses(trip_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        rows = conn.execute(
            """SELECT e.id, e.trip_id, e.description, e.amount, e.currency,
                      e.created_by, e.created_at, e.updated_at,
                      u.username AS created_by_username
               FROM trip_expenses e
               LEFT JOIN users u ON u.id = e.created_by
               WHERE e.trip_id = ?
               ORDER BY e.created_at ASC""",
            (trip_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class ExpenseBody(BaseModel):
    description: str
    amount: float
    currency: str


class ExpenseUpdateBody(BaseModel):
    description: str | None = None
    amount: float | None = None
    currency: str | None = None


@router.post("/api/trips/{trip_id}/expenses", status_code=201)
def create_expense(trip_id: str, body: ExpenseBody, user: dict = Depends(get_current_user)):
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Description cannot be empty")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")
    currency = body.currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {body.currency}")

    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")

    expense_id = str(uuid.uuid4())
    now = now_iso()
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_expenses
                   (id, trip_id, description, amount, currency, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                expense_id,
                trip_id,
                body.description.strip(),
                body.amount,
                currency,
                user["id"],
                now,
                now,
            ),
        )
    return {"id": expense_id, "ok": True}


@router.patch("/api/trips/{trip_id}/expenses/{expense_id}")
def update_expense(
    trip_id: str,
    expense_id: str,
    body: ExpenseUpdateBody,
    user: dict = Depends(get_current_user),
):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        expense = conn.execute(
            "SELECT id FROM trip_expenses WHERE id = ? AND trip_id = ?",
            (expense_id, trip_id),
        ).fetchone()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    updates: dict = {}
    if body.description is not None:
        if not body.description.strip():
            raise HTTPException(status_code=400, detail="Description cannot be empty")
        updates["description"] = body.description.strip()
    if body.amount is not None:
        if body.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be greater than zero")
        updates["amount"] = body.amount
    if body.currency is not None:
        currency = body.currency.upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise HTTPException(status_code=400, detail=f"Unsupported currency: {body.currency}")
        updates["currency"] = currency

    if not updates:
        return {"ok": True}

    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_write() as conn:
        conn.execute(
            f"UPDATE trip_expenses SET {set_clause} WHERE id = ? AND trip_id = ?",
            list(updates.values()) + [expense_id, trip_id],
        )
    return {"ok": True}


@router.delete("/api/trips/{trip_id}/expenses/{expense_id}", status_code=204)
def delete_expense(trip_id: str, expense_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        expense = conn.execute(
            "SELECT id FROM trip_expenses WHERE id = ? AND trip_id = ?",
            (expense_id, trip_id),
        ).fetchone()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    with db_write() as conn:
        conn.execute(
            "DELETE FROM trip_expenses WHERE id = ? AND trip_id = ?",
            (expense_id, trip_id),
        )
    return None
