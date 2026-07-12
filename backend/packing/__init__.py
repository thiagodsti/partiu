"""
Trip packing-list feature package.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to PackingService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - PackingRepository: CRUD for the `packing_items` table
  service.py        - PackingService: trip-access checks + validation rules

``packing_service`` is a module-level singleton — routes.py depends on it rather than
reaching into the repository directly.
"""

from .service import packing_service

__all__ = ["packing_service"]
