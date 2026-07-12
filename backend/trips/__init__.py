"""
Trips feature package (trip CRUD, listing/search, merge, flight assignment,
destination image, Immich album linking, rating, note, iCalendar export).

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to TripService
  dto.py          - request/response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  errors.py       - a single parametrized TripError(message, status_code) — like
                     auth, this feature has many distinct (message, status) pairs
                     and nothing downstream needs to tell them apart by type
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - TripRepository: CRUD for `trips` + the bulk joins needed to
                       enrich a trip (flight counts, owner usernames, expense
                       totals, Immich album links, search index)
  service.py         - TripService: listing/search assembly, CRUD, merge,
                          flight assignment, rating/note
  ical_service.py    - IcalService: .ics generation (self-contained, unrelated
                          to trip CRUD)
  image_service.py   - TripImageService: destination-photo fetch/refresh
                          (Wikipedia), kept separate from trip CRUD
  immich_service.py  - TripImmichService: Immich album create/check
                          orchestration, kept separate from trip CRUD

Trip sharing (invitations, per-trip collaborator list, trusted users) is a
related but distinct concern, split into its own sibling files rather than
its own top-level package — its URLs are almost entirely under /api/trips
already, and it has no reason to compete for the "shares" name with the
cross-cutting authorization helpers in ..auth.access:
  sharing_domain.py    - Invitation, TripShare, TrustedUser, ShareRecord
  sharing_dto.py       - request/response models for sharing_routes.py
  sharing_errors.py    - ShareError subclasses translated to HTTP by routes
  sharing_mappers.py   - sqlite3.Row -> domain, domain -> DTO conversions
  sharing_repository.py - ShareRepository: CRUD for `trip_shares` and
                            `trusted_users`
  sharing_service.py   - ShareService: ownership checks + sharing/trust rules
  sharing_routes.py    - FastAPI router; delegates to ShareService

Each service above is its own module-level singleton — routes.py depends on
them rather than reaching into the repository directly. The
`/api/trips/{id}/flights/{id}` assign/unassign endpoints live in service.py
(not in the flights feature) because they're trip-centric operations,
matching the original route's placement.
"""

from .ical_service import ical_service
from .image_service import trip_image_service
from .immich_service import trip_immich_service
from .service import trip_service
from .sharing_service import share_service

__all__ = [
    "ical_service",
    "share_service",
    "trip_image_service",
    "trip_immich_service",
    "trip_service",
]
