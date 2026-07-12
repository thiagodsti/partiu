"""
Travel-statistics feature package.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to StatsService
  dto.py          - response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - StatsRepository: read-only queries over `flights`/`airports`/`trips`
  service.py         - StatsService: distance/CO2/top-N/visited-countries computation
                        (also exposes ``_haversine``/``_co2_kg`` as plain functions, unit
                        tested directly)

``stats_service`` is a module-level singleton — routes.py depends on it rather than
reaching into the repository directly.
"""

from .service import stats_service

__all__ = ["stats_service"]
