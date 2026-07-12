"""
Trip expenses feature package.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to ExpenseService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects + SUPPORTED_CURRENCIES (also used by settings.py
                     to validate a user's default currency)
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - ExpenseRepository: CRUD for the `trip_expenses` table
  service.py        - ExpenseService: trip-access checks + validation rules

``expense_service`` is a module-level singleton — routes.py depends on it rather than
reaching into the repository directly.
"""

from .domain import SUPPORTED_CURRENCIES
from .service import expense_service

__all__ = ["SUPPORTED_CURRENCIES", "expense_service"]
