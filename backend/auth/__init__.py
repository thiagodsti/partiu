"""
Auth package. Two responsibilities:

1. Cross-cutting session/password/authorization helpers — ``get_current_user``,
   ``require_admin``, ``hash_password``, ``verify_password``, ``has_any_users``,
   ``get_user_imap_settings``, ``validate_secret_key`` (session.py), plus
   ``can_access_trip``, ``is_trip_owner``, ``can_access_flight``, ``refuse_on_demo``
   (access.py) —
   re-exported here because the rest of the backend imports them as
   ``from ..auth import get_current_user`` / ``from ..auth import can_access_trip``
   (literally every route/service module). Keeping that import path stable is why
   this stayed a single top-level ``auth`` package instead of being renamed.

2. The auth feature itself (setup/login/2FA/logout/me/change-password), layered as
   routes -> service -> repository -> database like the other features:
     routes.py       - FastAPI router; only HTTP concerns, delegates to AuthService
                        and TwoFAService
     dto.py          - request/response models used at the HTTP boundary (routes)
     domain.py       - plain domain objects used by the service/repository
     errors.py       - a single parametrized AuthError(message, status_code) — this
                        feature has far more distinct (message, status) pairs than
                        others, and nothing downstream needs to tell them apart by type
     mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
     repository.py    - AuthRepository: the `users` columns this feature needs, plus
                          the `auth_attempts` table (TOTP lockout)
     service.py         - AuthService: setup/login (+ lockout)/logout/me/
                             change-password; owns the in-memory per-IP
                             login-lockout state (must be a singleton for the
                             same reason sync's lock is)
     twofa_service.py    - TwoFAService: 2FA setup/enable/disable/verify, kept
                             separate from service.py as its own concern

``auth_service`` and ``twofa_service`` are module-level singletons — routes.py
depends on them rather than reaching into the repository directly.
"""

from .access import can_access_flight, can_access_trip, is_trip_owner, refuse_on_demo
from .service import auth_service
from .session import (
    get_current_user,
    get_user_imap_settings,
    has_any_users,
    hash_password,
    require_admin,
    validate_secret_key,
    verify_password,
)
from .twofa_service import twofa_service

__all__ = [
    "auth_service",
    "can_access_flight",
    "can_access_trip",
    "get_current_user",
    "get_user_imap_settings",
    "has_any_users",
    "hash_password",
    "is_trip_owner",
    "refuse_on_demo",
    "require_admin",
    "twofa_service",
    "validate_secret_key",
    "verify_password",
]
