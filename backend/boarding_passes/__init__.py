"""
Boarding-passes feature package.

Layering (routes -> service -> repository -> database + file storage):
  routes.py       - FastAPI router; only HTTP concerns, delegates to BoardingPassService
  dto.py          - response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  errors.py       - domain error types shared by repository.py and service.py, translated
                     to HTTP responses by routes.py
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - BoardingPassRepository: CRUD for the `boarding_passes` table +
                       the on-disk image files
  service.py        - BoardingPassService: trip/flight-access checks + upload validation

``boarding_pass_service`` is a module-level singleton — routes.py and sync/pipeline.py both
depend on it rather than reaching into the repository directly.
"""

from .service import boarding_pass_service

__all__ = ["boarding_pass_service"]
