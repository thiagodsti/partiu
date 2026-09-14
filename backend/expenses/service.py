"""Use cases for trip expenses: trip-access checks, validation, paid_by/participants
resolution and balance computation."""

import uuid

from .domain import (
    SUPPORTED_CURRENCIES,
    BalanceEntry,
    BudgetStatus,
    Expense,
    ParticipantRef,
)
from .errors import ExpenseNotFoundError, TripAccessError
from .repository import BudgetRepository, ExpenseRepository

__all__ = ["ExpenseNotFoundError", "ExpenseService", "TripAccessError", "expense_service"]


class ExpenseService:
    def __init__(
        self,
        repository: ExpenseRepository | None = None,
        budget_repository: BudgetRepository | None = None,
    ):
        self._repository = repository or ExpenseRepository()
        self._budgets = budget_repository or BudgetRepository()

    def list_expenses(self, trip_id: str, user_id: int) -> list[Expense]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def list_participants_for_trip(self, trip_id: str, user_id: int) -> list[ParticipantRef]:
        """Everyone who can be picked as payer/participant on this trip: the trip
        owner, its accepted collaborators, and guests already tagged on this
        specific trip. Guests are scoped per trip — a guest added on one trip
        does not show up as a suggestion on an unrelated one."""
        self._check_access(trip_id, user_id)

        from ..trips.repository import TripRepository
        from ..trips.sharing_repository import ShareRepository
        from .guests_service import guest_service

        trip_repo = TripRepository()
        trip = trip_repo.get_by_id(trip_id)

        participants: list[ParticipantRef] = []
        if trip is not None and trip.user_id is not None:
            owner_username = trip_repo.get_owner_username(trip.user_id)
            if owner_username:
                participants.append(
                    ParticipantRef(type="user", id=trip.user_id, name=owner_username)
                )

        share_repo = ShareRepository()
        for share in share_repo.list_shares_for_trip(trip_id):
            if share.status == "accepted":
                participants.append(
                    ParticipantRef(type="user", id=share.user_id, name=share.username)
                )

        for guest in guest_service.list_for_trip(trip_id, user_id):
            participants.append(ParticipantRef(type="guest", id=guest.id, name=guest.name))

        return participants

    def _acceptable_choices(
        self, trip_id: str, user_id: int, trip_participants: list[ParticipantRef]
    ) -> list[ParticipantRef]:
        """`trip_participants` plus the caller's own guests, even ones not yet
        tagged on this trip — needed so a guest that was just quick-added (and
        therefore isn't "trip-referenced" yet, since no expense names them)
        can immediately be used as that first expense's payer/participant."""
        from .guests_service import guest_service

        seen = {(p.type, p.id) for p in trip_participants}
        choices = list(trip_participants)
        for guest in guest_service.list_mine(user_id):
            if ("guest", guest.id) not in seen:
                choices.append(ParticipantRef(type="guest", id=guest.id, name=guest.name))
                seen.add(("guest", guest.id))
        return choices

    def create_expense(
        self,
        trip_id: str,
        user_id: int,
        description: str,
        amount: float,
        currency: str,
        paid_by: tuple[str, int] | None = None,
        participants: list[tuple[str, int]] | None = None,
    ) -> str:
        """Validate then create an expense, returning its id.

        Field validation runs before the trip-access check (matches the original
        route's behavior: bad input on someone else's trip returns 400, not 404).
        The access check itself happens inside list_participants_for_trip below.
        paid_by defaults to the creator; participants default to everyone
        currently on the trip.
        """
        clean_description = self._validate_description(description)
        self._validate_amount(amount)
        clean_currency = self._validate_currency(currency)

        trip_participants = self.list_participants_for_trip(trip_id, user_id)
        valid_choices = self._acceptable_choices(trip_id, user_id, trip_participants)
        paid_by_type, paid_by_id = self._resolve_paid_by(paid_by, user_id, valid_choices)
        resolved_participants = self._resolve_participants(
            participants, trip_participants, valid_choices
        )

        expense_id = str(uuid.uuid4())
        self._repository.create(
            expense_id,
            trip_id,
            clean_description,
            amount,
            clean_currency,
            user_id,
            paid_by_id if paid_by_type == "user" else None,
            paid_by_id if paid_by_type == "guest" else None,
            resolved_participants,
        )
        return expense_id

    def update_expense(
        self,
        trip_id: str,
        expense_id: str,
        user_id: int,
        description: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
        paid_by: tuple[str, int] | None = None,
        participants: list[tuple[str, int]] | None = None,
    ) -> None:
        self._check_access(trip_id, user_id)
        if not self._repository.exists(expense_id, trip_id):
            raise ExpenseNotFoundError(expense_id)

        updates: dict = {}
        if description is not None:
            updates["description"] = self._validate_description(description)
        if amount is not None:
            self._validate_amount(amount)
            updates["amount"] = amount
        if currency is not None:
            updates["currency"] = self._validate_currency(currency)

        trip_participants: list[ParticipantRef] = []
        valid_choices: list[ParticipantRef] = []
        if paid_by is not None or participants is not None:
            trip_participants = self.list_participants_for_trip(trip_id, user_id)
            valid_choices = self._acceptable_choices(trip_id, user_id, trip_participants)

        if paid_by is not None:
            paid_by_type, paid_by_id = self._resolve_paid_by(paid_by, user_id, valid_choices)
            updates["paid_by_user_id"] = paid_by_id if paid_by_type == "user" else None
            updates["paid_by_guest_id"] = paid_by_id if paid_by_type == "guest" else None

        if updates:
            self._repository.update(expense_id, trip_id, updates)

        if participants is not None:
            resolved_participants = self._resolve_participants(
                participants, trip_participants, valid_choices
            )
            self._repository.replace_participants(expense_id, resolved_participants)

    def delete_expense(self, trip_id: str, expense_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if not self._repository.exists(expense_id, trip_id):
            raise ExpenseNotFoundError(expense_id)
        self._repository.delete(expense_id, trip_id)

    def get_balances(self, trip_id: str, user_id: int) -> dict[str, list[BalanceEntry]]:
        """Net balance per participant per currency: what they paid minus their
        equal share of every expense they're tagged in. Positive = owed to them,
        negative = they owe."""
        self._check_access(trip_id, user_id)
        expenses = self._repository.list_for_trip(trip_id)

        per_currency: dict[str, dict[tuple[str, int], BalanceEntry]] = {}
        for expense in expenses:
            bucket = per_currency.setdefault(expense.currency, {})
            self._credit(bucket, expense.paid_by, expense.amount)

            if not expense.participants:
                continue
            share = expense.amount / len(expense.participants)
            for participant in expense.participants:
                self._credit(bucket, participant, -share)

        return {
            currency: sorted(entries.values(), key=lambda b: b.name.lower())
            for currency, entries in per_currency.items()
        }

    # -- Budget ---------------------------------------------------------------

    def get_budget(self, trip_id: str, user_id: int) -> BudgetStatus:
        """The caller's budget for this trip, and what they have spent against it.

        Spend is the caller's **own share**: an expense split four ways counts a
        quarter of it, whoever paid. What you paid out is a cash-flow question
        and the balances view already answers it; a budget is about what the
        trip costs you.

        Only expenses in the budget's own currency count. Anything else is
        returned in `uncounted`, named rather than converted — there are no
        exchange rates in this app. With no budget set, every currency the
        caller has a share in lands in `uncounted`, so the UI can offer to set
        one against a number the traveller already recognises.
        """
        self._check_access(trip_id, user_id)
        budget = self._budgets.get(trip_id, user_id)
        share = self._own_share_by_currency(trip_id, user_id)

        if budget is None:
            return BudgetStatus(budget=None, spent=0.0, uncounted=share)

        spent = share.pop(budget.currency, 0.0)
        return BudgetStatus(budget=budget, spent=spent, uncounted=share)

    def set_budget(self, trip_id: str, user_id: int, amount: float, currency: str) -> None:
        self._check_access(trip_id, user_id)
        if amount <= 0:
            raise ValueError("Budget must be greater than zero")
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}")
        self._budgets.set(trip_id, user_id, amount, currency)

    def clear_budget(self, trip_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        self._budgets.delete(trip_id, user_id)

    def budgets_for_trips(self, user_id: int, trip_ids: list[str]) -> dict[str, BudgetStatus]:
        """The caller's budget and spend for each of these trips, in two reads.

        For the trips list, which renders a card per trip: fetching a budget per
        card would be a request per row. Only trips the caller has actually set
        a budget on come back — a card with no budget has nothing to show.

        No access check here: the caller's own `trip_budgets` rows are scoped to
        them by definition, and the list has already decided which trips they
        may see.
        """
        budgets = self._budgets.list_for_user(user_id, trip_ids)
        if not budgets:
            return {}

        shares = self._budgets.own_share_by_trip(user_id, list(budgets))
        out: dict[str, BudgetStatus] = {}
        for trip_id, budget in budgets.items():
            uncounted = {
                currency: amount
                for (t, currency), amount in shares.items()
                if t == trip_id and currency != budget.currency
            }
            out[trip_id] = BudgetStatus(
                budget=budget,
                spent=shares.get((trip_id, budget.currency), 0.0),
                uncounted=uncounted,
            )
        return out

    def _own_share_by_currency(self, trip_id: str, user_id: int) -> dict[str, float]:
        """Per-currency total of the caller's equal share of what they are in.

        An expense the caller is not a participant of contributes nothing, even
        if they paid it — they are settling up for other people, not spending on
        themselves. An expense with no participants at all contributes nothing
        rather than dividing by zero.
        """
        share: dict[str, float] = {}
        for expense in self._repository.list_for_trip(trip_id):
            if not expense.participants:
                continue
            if not any(p.type == "user" and p.id == user_id for p in expense.participants):
                continue
            share[expense.currency] = share.get(expense.currency, 0.0) + expense.amount / len(
                expense.participants
            )
        return share

    @staticmethod
    def _credit(
        bucket: dict[tuple[str, int], BalanceEntry], participant: ParticipantRef, amount: float
    ) -> None:
        key = (participant.type, participant.id)
        entry = bucket.get(key)
        if entry is None:
            entry = BalanceEntry(
                type=participant.type, id=participant.id, name=participant.name, net=0.0
            )
            bucket[key] = entry
        entry.net += amount

    @staticmethod
    def _resolve_paid_by(
        paid_by: tuple[str, int] | None, user_id: int, valid_choices: list[ParticipantRef]
    ) -> tuple[str, int]:
        if paid_by is None:
            return "user", user_id
        paid_by_type, paid_by_id = paid_by
        if paid_by_type not in ("user", "guest"):
            raise ValueError(f"Invalid paid_by type: {paid_by_type}")
        if not any(p.type == paid_by_type and p.id == paid_by_id for p in valid_choices):
            raise ValueError("paid_by is not a valid participant on this trip")
        return paid_by_type, paid_by_id

    @staticmethod
    def _resolve_participants(
        participants: list[tuple[str, int]] | None,
        defaults_from: list[ParticipantRef],
        valid_choices: list[ParticipantRef],
    ) -> list[tuple[str, int]]:
        if participants is None:
            return [(p.type, p.id) for p in defaults_from]
        valid_keys = {(p.type, p.id) for p in valid_choices}
        for ptype, pid in participants:
            if ptype not in ("user", "guest"):
                raise ValueError(f"Invalid participant type: {ptype}")
            if (ptype, pid) not in valid_keys:
                raise ValueError("participants includes someone not on this trip")
        # de-duplicate while preserving order
        seen: set[tuple[str, int]] = set()
        result: list[tuple[str, int]] = []
        for p in participants:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    @staticmethod
    def _validate_description(description: str) -> str:
        clean = description.strip()
        if not clean:
            raise ValueError("Description cannot be empty")
        return clean

    @staticmethod
    def _validate_amount(amount: float) -> None:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")

    @staticmethod
    def _validate_currency(currency: str) -> str:
        upper = currency.upper()
        if upper not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency: {currency}")
        return upper

    def _check_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


expense_service = ExpenseService()
