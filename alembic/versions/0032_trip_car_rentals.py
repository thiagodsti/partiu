"""Add trip_car_rentals — a hired vehicle held over a span of a trip.

The one trip component this app modelled nowhere. Measured across the 372-email
corpus there are three real rental confirmations from three vendors — Hertz,
Sixt and Europcar — and all three senders sat in `_NON_FLIGHT_DOMAINS`, silently
skipped.

**Not a `trip_segments` row**, though `type = 'car'` already exists there and
looks like the obvious home. That type is a *drive*: two places, a direction,
and a duration that is time spent travelling. A rental is a **contract over a
span** — you collect the car at 09:30 on the 29th and hand it back at 23:00 on
the 1st, and what happens in between is several drives, or none. Forcing it into
a segment would mean `duration_minutes` holding four days of *not* travelling,
`TripMap` drawing a dashed leg between two points you did not travel between at
those times (and, for the common same-place rental, a line from a point to
itself), and `splitTransport` sorting a standing contract into Outbound or
Return. That is the same argument 0024 made for keeping stays off
`trip_segments`, and it applies here for the same reason: the shape does not
fit, and the first consumer that forgets to guard is the bug.

A rental and a drive are complements, not alternatives — the rental says what
you hired, a `car` segment says where you took it — so an itinerary can hold
both and they render in different sections.

**Two places, unlike a stay.** One-way rentals are not exotic: two of the three
measured bookings were one-way (Munich→Vienna, Trapani→Catania). Collapsing the
ends to one place would have been wrong for the majority of the corpus.

`pickup_date` / `dropoff_date` denormalise the **local calendar date at each
counter** alongside the UTC instants, for exactly the reasons 0024 gives: SQLite
cannot convert timezones, so `_recompute_span` reading `DATE(pickup_datetime)`
would land on the wrong day for a counter far enough west, and the day planner
bands the rental across days off these strings without doing zone maths in the
browser. Both ends get their own, because a one-way rental can cross a zone.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_car_rentals (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            vendor TEXT NOT NULL,
            pickup_place TEXT NOT NULL,
            pickup_address TEXT,
            pickup_lat REAL,
            pickup_lon REAL,
            pickup_timezone TEXT,
            pickup_country TEXT,
            pickup_datetime TEXT NOT NULL,
            pickup_date TEXT NOT NULL,
            dropoff_place TEXT NOT NULL,
            dropoff_address TEXT,
            dropoff_lat REAL,
            dropoff_lon REAL,
            dropoff_timezone TEXT,
            dropoff_country TEXT,
            dropoff_datetime TEXT NOT NULL,
            dropoff_date TEXT NOT NULL,
            booking_reference TEXT,
            vehicle TEXT,
            driver_name TEXT,
            notes TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_car_rentals_trip ON trip_car_rentals(trip_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_car_rentals_pickup ON trip_car_rentals(pickup_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_car_rentals")
