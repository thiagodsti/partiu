"""
App-settings feature package (per-user Gmail/IMAP/Immich/currency config, admin-only
global sync/SMTP config, airport count/reload, non-flight-domain admin list).

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to SettingsService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  errors.py       - domain error types translated to HTTP responses by routes.py
  mappers.py      - domain -> DTO conversions
  repository.py    - SettingsRepository: global_settings + per-user column reads/writes,
                       airport count/reload, non-flight-domain blocklist CRUD
  service.py         - SettingsService: validation (incl. SSRF checks on IMAP host /
                          Immich URL), IMAP/Immich connectivity tests, non-flight-domain
                          admin management

``settings_service`` is a module-level singleton — routes.py depends on it rather than
reaching into the repository directly.
"""

from .service import settings_service

__all__ = ["settings_service"]
