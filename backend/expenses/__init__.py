"""
Trip expenses feature package. Two sub-features share this package: expenses
themselves, and guests (a per-user address book of non-account trip participants
used for splitting expenses).

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router for expenses; only HTTP concerns, delegates to ExpenseService
  dto.py          - request/response models used at the expenses HTTP boundary
  domain.py       - plain domain objects (Expense, ParticipantRef, BalanceEntry, Guest) +
                     SUPPORTED_CURRENCIES (also used by settings.py to validate a user's
                     default currency)
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions (expenses)
  repository.py    - ExpenseRepository: CRUD for `trip_expenses` + `trip_expense_participants`
  service.py        - ExpenseService: trip-access checks, validation, paid_by/participants
                       resolution, and balance computation
  errors.py          - exceptions shared by both sub-features (TripAccessError, etc.)

  guests_routes.py    - FastAPI router for guests
  guests_dto.py        - request/response models used at the guests HTTP boundary
  guests_mappers.py     - domain -> DTO conversions (guests)
  guests_repository.py   - GuestRepository: CRUD for the `guests` table
  guests_service.py       - GuestService: ownership checks + trip-scoped guest picker

``expense_service`` and ``guest_service`` are module-level singletons — routes depend on
them rather than reaching into repositories directly.
"""

from .domain import SUPPORTED_CURRENCIES
from .guests_service import guest_service
from .service import expense_service

__all__ = ["SUPPORTED_CURRENCIES", "expense_service", "guest_service"]
