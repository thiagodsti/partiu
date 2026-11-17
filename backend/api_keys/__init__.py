"""
Personal API keys feature package.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to ApiKeyService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - ApiKeyRepository: CRUD for the `api_keys` table
  service.py        - ApiKeyService: minting, hashing, expiry, and the rule for
                       which requests a key may make at all

``api_key_service`` is a module-level singleton. ``auth/session.py`` calls it from
``get_current_user`` when a request carries ``Authorization: Bearer``.
"""

from .service import api_key_service

__all__ = ["api_key_service"]
