"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import BalanceEntry, Expense, ParticipantRef
from .dto import BalanceEntryDTO, ExpenseDTO, ParticipantDTO


def row_to_paid_by(row: sqlite3.Row) -> ParticipantRef:
    if row["paid_by_user_id"] is not None:
        return ParticipantRef(type="user", id=row["paid_by_user_id"], name=row["paid_by_user_name"])
    return ParticipantRef(type="guest", id=row["paid_by_guest_id"], name=row["paid_by_guest_name"])


def row_to_participant_ref(row: sqlite3.Row) -> ParticipantRef:
    if row["user_id"] is not None:
        return ParticipantRef(type="user", id=row["user_id"], name=row["user_name"])
    return ParticipantRef(type="guest", id=row["guest_id"], name=row["guest_name"])


def row_to_expense(row: sqlite3.Row, participant_rows: list[sqlite3.Row]) -> Expense:
    return Expense(
        id=row["id"],
        trip_id=row["trip_id"],
        description=row["description"],
        amount=row["amount"],
        currency=row["currency"],
        created_by=row["created_by"],
        created_by_username=row["created_by_username"],
        paid_by=row_to_paid_by(row),
        participants=[row_to_participant_ref(p) for p in participant_rows],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def participant_to_dto(participant: ParticipantRef) -> ParticipantDTO:
    return ParticipantDTO(type=participant.type, id=participant.id, name=participant.name)


def expense_to_dto(expense: Expense) -> ExpenseDTO:
    return ExpenseDTO(
        id=expense.id,
        trip_id=expense.trip_id,
        description=expense.description,
        amount=expense.amount,
        currency=expense.currency,
        created_by=expense.created_by,
        created_by_username=expense.created_by_username,
        paid_by=participant_to_dto(expense.paid_by),
        participants=[participant_to_dto(p) for p in expense.participants],
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def balance_entry_to_dto(entry: BalanceEntry) -> BalanceEntryDTO:
    return BalanceEntryDTO(type=entry.type, id=entry.id, name=entry.name, net=entry.net)
