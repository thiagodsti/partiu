"""
Airport reference-data package (search/lookup routes + the `airports` table).

Deliberately lighter than the full routes -> service -> repository layering used
by other feature packages: both endpoints are read-only, unauthenticated lookups
with no business logic to speak of, so routes.py talks to AirportRepository directly.

  repository.py - AirportRepository: reads for the `airports` table
  routes.py     - FastAPI router; GET /api/airports/search, GET /api/airports/{iata}
  timezone.py   - Airport-coordinate-derived timezone lookup and local->UTC datetime
                    conversion (localize_to_utc, apply_airport_timezones); uses
                    AirportRepository. Lives here rather than in a generic utils
                    package because it touches the database, and not inside flights/
                    because parsers/ needs it too and parsers/flights are kept
                    independent of each other — airports/ is neutral ground both
                    can depend on.

Other packages (parsers/, sync/grouping.py, trips/, settings/) still query the
`airports` table directly for their own narrow needs (city name joins, admin
reload/count) rather than going through this repository — consolidating those
is a separate, larger cleanup.
"""
