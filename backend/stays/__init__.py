"""
Trip stays feature package — accommodation (hotels, Airbnbs, hostels) booked
for a trip, entered by hand alongside its flights and ground segments.

There is deliberately no email parsing here yet: `sync/pipeline.py` blocks
airbnb.com and booking.com outright as flight-sync noise, and a stay has no
route for `parsers/validation.py` to sanity-check, so importing one is a second
extraction target rather than one more airline rule. Stays are manual for now.

Layering (routes -> service -> repository -> database), mirroring `segments/`:
  routes.py     - FastAPI router for /api/trips/{trip_id}/stays
  dto.py        - request/response models used at the HTTP boundary
  domain.py     - plain domain objects (Stay, StayPlace) + STAY_KINDS
  mappers.py    - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py - StayRepository: CRUD for `trip_stays`
  service.py    - StayService: trip-access checks, validation, local->UTC
                  conversion and the local check-in/check-out *dates*
  errors.py     - TripAccessError, StayNotFoundError

What this package does NOT enforce: that a stay falls inside the trip's dates.
The span is derived from the trip's contents (`TripRepository._recompute_span`),
so "must be within the trip" is circular — and it would reject the airport hotel
the night before an early departure, which is a real booking. Stays *extend* the
span instead; anything merely odd is a non-blocking warning in the UI.

``stay_service`` is a module-level singleton — routes depend on it rather than
reaching into the repository directly.
"""

from .domain import STAY_KINDS
from .service import stay_service

__all__ = ["STAY_KINDS", "stay_service"]
