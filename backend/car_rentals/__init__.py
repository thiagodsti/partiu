"""Car-rental feature package — a hired vehicle held over a span of a trip.

A **separate table from `trip_segments`**, though `type = 'car'` already exists
there. That type is a *drive*: two places, a direction, and a duration that is
time spent travelling. A rental is a contract over a span — collected on the
29th, handed back on the 1st, with several drives or none in between — so
reusing a segment would put four days of *not* travelling in `duration_minutes`,
draw a `TripMap` line between two points nobody travelled between at those
times (and, for the common same-place rental, a line from a point to itself),
and sort a standing contract into Outbound or Return. Migration 0032 sets this
out at length; it is the same argument 0024 used to keep stays off segments.

The two are complements: the rental says what was hired, a `car` segment says
where it was taken. A trip can hold both, and they render in different sections.

Unlike a stay this has **two** places, because one-way rentals are ordinary —
two of the three bookings in the measured email corpus were one-way.

Layering (routes -> service -> repository -> database), mirroring `stays/`:
  routes.py     - FastAPI router for /api/trips/{trip_id}/car-rentals
  dto.py        - request/response models used at the HTTP boundary
  domain.py     - CarRental, RentalPlace, MAX_DAYS
  mappers.py    - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py - CarRentalRepository: CRUD for `trip_car_rentals`
  service.py    - CarRentalService: access checks, validation, local->UTC
                  conversion and the local pickup/drop-off *dates*
  errors.py     - TripAccessError, CarRentalNotFoundError

Email import lives in `sync/car_rentals_import.py`, beside the lodging importer
and for the same reason: which trip a booking belongs to is a sync concern.

``car_rental_service`` is a module-level singleton — routes depend on it rather
than reaching into the repository directly.
"""

from .service import car_rental_service

__all__ = ["car_rental_service"]
