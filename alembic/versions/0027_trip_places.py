"""A trip's origin and destination as places, not airport codes.

`trips.origin_airport` / `destination_airport` are **derived**: `_recompute_span`
rewrites both from the trip's flights on every mutation and nulls them when
there are none. That is correct for what they are — a summary of the flights —
but it means they can never hold something a person typed, and it leaves every
trip that is not flown with no ends at all. A Florianópolis → São Paulo drive
has a real origin and a real destination; neither is an airport.

So these columns are a separate, **user-owned** pair. Nothing recomputes them.
They carry coordinates and a country code alongside the name for the same reason
`trip_segments` and `trip_stays` do: the country is what makes the place count
as visited, and it is recorded from the geocoder result the user picked rather
than inferred later from the coordinates (migration 0025 has the Malmö-in-
Denmark story behind that rule).

The destination place also becomes the cover photo's subject, ahead of the
destination airport's city. That is what finally gives a rail or road trip a
photo — the Wikipedia lookup could only ever resolve an IATA code before.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("origin_place", "TEXT"),
    ("origin_lat", "REAL"),
    ("origin_lon", "REAL"),
    ("origin_country", "TEXT"),
    ("destination_place", "TEXT"),
    ("destination_lat", "REAL"),
    ("destination_lon", "REAL"),
    ("destination_country", "TEXT"),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.execute(f"ALTER TABLE trips ADD COLUMN {name} {type_}")


def downgrade() -> None:
    for name, _ in _COLUMNS:
        op.execute(f"ALTER TABLE trips DROP COLUMN {name}")
