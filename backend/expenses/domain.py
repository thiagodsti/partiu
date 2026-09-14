"""Domain object + shared constants for the trip-expenses feature."""

from dataclasses import dataclass
from typing import Literal

ParticipantType = Literal["user", "guest"]


@dataclass
class Budget:
    """One person's spending limit for one trip, in one currency."""

    amount: float
    currency: str


@dataclass
class BudgetStatus:
    """A budget alongside what the caller has actually committed to it.

    `spent` counts **the caller's own share** of every expense they are tagged
    in — an expense split four ways counts a quarter, whoever paid. A budget is
    what the trip costs you, and that does not depend on who held the card.

    `uncounted` is per-currency spend that falls outside the budget's currency.
    It is reported rather than converted: there are no exchange rates here, and
    a converted figure would be a guess wearing the clothes of a fact.
    """

    budget: Budget | None
    spent: float
    uncounted: dict[str, float]


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


@dataclass
class ParticipantRef:
    """A reference to whoever is involved in an expense — a real user or a guest."""

    type: ParticipantType
    id: int
    name: str


@dataclass
class Expense:
    id: str
    trip_id: str
    description: str
    amount: float
    currency: str
    created_by: int | None
    created_by_username: str | None
    paid_by: ParticipantRef
    participants: list[ParticipantRef]
    created_at: str
    updated_at: str


@dataclass
class BalanceEntry:
    type: ParticipantType
    id: int
    name: str
    net: float


@dataclass
class Guest:
    id: int
    owner_id: int
    name: str
    created_at: str
