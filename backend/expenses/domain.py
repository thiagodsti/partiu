"""Domain object + shared constants for the trip-expenses feature."""

from dataclasses import dataclass
from typing import Literal

ParticipantType = Literal["user", "guest"]

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
