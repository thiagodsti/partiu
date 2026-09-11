"""
Trip segments feature package — manually-added non-flight transport legs
(train, bus, ferry, car) that sit on a trip alongside its flights.

There is deliberately no email parsing here: segments are entered by hand. That
is also why `trip_id` is NOT NULL, unlike `flights`, which can exist unattached
while the sync pipeline groups them.

Layering (routes -> service -> repository -> database):
  routes.py     - FastAPI router for segments + the station type-ahead endpoint
  dto.py        - request/response models used at the HTTP boundary
  domain.py     - plain domain objects (Segment, Place) + SEGMENT_TYPES
  mappers.py    - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py - SegmentRepository: CRUD for `trip_segments`
  service.py    - SegmentService: trip-access checks, validation, local->UTC
                  conversion via the station's coordinates
  errors.py     - TripAccessError, SegmentNotFoundError

Station lookup itself lives in ``integrations/photon/`` — this package calls it
as a client, the same way trips/ calls the Immich and Wikipedia clients.

``segment_service`` is a module-level singleton — routes depend on it rather
than reaching into the repository directly.
"""

from .domain import SEGMENT_TYPES
from .service import segment_service

__all__ = ["SEGMENT_TYPES", "segment_service"]
