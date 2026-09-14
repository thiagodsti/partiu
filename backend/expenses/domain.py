"""Domain object + shared constants for the trip-expenses feature."""

from dataclasses import dataclass, field
from typing import Literal

ParticipantType = Literal["user", "guest"]


@dataclass
class ParticipantRef:
    """A reference to whoever is involved in an expense — a real user or a guest."""

    type: ParticipantType
    id: int
    name: str


@dataclass
class Budget:
    """A spending limit for one trip, in one currency, belonging to the people
    named in `members`.

    Usually that is one person — the owner alone, which is what every budget
    written before migration 0031 is. When it names more, the budget is a shared
    purse: spend is the **sum of every member's share**, so it makes no
    difference which of them held the card. A member can be a `guest`, since the
    companion you share a budget with often has no account of their own.

    `owner_user_id` is who created it. It matters only for storage and for
    saying whose budget a member is looking at — a member may edit it, and the
    owner never changes when they do.
    """

    amount: float
    currency: str
    owner_user_id: int = 0
    owner_username: str | None = None
    members: list[ParticipantRef] = field(default_factory=list)


@dataclass
class BudgetStatus:
    """A budget alongside what the caller has actually committed to it.

    `spent` counts the **budget members'** combined share of every expense any
    of them is tagged in — an expense split four ways between four people counts
    a quarter to a solo budget and a half to one shared by two of them, whoever
    paid. A budget is what the trip costs the people it belongs to, and that
    does not depend on who held the card.

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
