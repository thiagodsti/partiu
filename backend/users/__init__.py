"""
Admin user-management feature package.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to UserService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  errors.py       - domain error types translated to HTTP responses by routes.py
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - UserRepository: CRUD for the `users` table
  service.py         - UserService: validation + audit logging (backend.auth.audit_log.audit)

``user_service`` is a module-level singleton — routes.py depends on it rather than
reaching into the repository directly.
"""

from .service import user_service

__all__ = ["user_service"]
