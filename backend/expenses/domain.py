"""Domain object + shared constants for the trip-expenses feature."""

from dataclasses import dataclass

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
    created_at: str
    updated_at: str
