"""
Trip day-notes (planner) feature package.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to DayNoteService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain object used by the service/repository
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - DayNoteRepository: CRUD for the `trip_day_notes` table
  service.py         - DayNoteService: trip-access checks + date-format validation

``day_note_service`` is a module-level singleton — routes.py depends on it rather than
reaching into the repository directly.
"""

from .service import day_note_service

__all__ = ["day_note_service"]
