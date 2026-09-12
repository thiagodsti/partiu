"""Add trip_stays — accommodation (hotels, Airbnbs, hostels) on a trip.

A separate table rather than `type = 'stay'` on `trip_segments`, even though
0023 deliberately left that door open by omitting the CHECK constraint. The
door was left open cheaply, not because the shape fits: `trip_segments` is
built around *two* places and a direction, and a stay is one place and a span.
Forcing it in would mean `departure_place` and `arrival_place` holding the same
string, `TripMap` drawing a dashed line from a point to itself, `duration_minutes`
reporting minutes where the unit is nights, and a `type != 'stay'` guard in
`splitTransport`, `SegmentRow` and every other segment consumer — the same
"first missed guard" argument 0023 used to keep ground transport off `flights`.

`check_in_date` / `check_out_date` denormalise the **local date at the property**
alongside the UTC instants. They are not redundant: SQLite cannot convert
timezones, so `_recompute_span`'s `DATE(check_in_datetime)` would read the wrong
day for a property far enough west (15:00 local at UTC-10 is 01:00Z the *next*
day). It also matters more here than for flights — a hotel booking's identity
*is* its local dates ("14-18 October"), not the instants — and it lets the day
planner band a stay across days without doing timezone maths in the browser.

`kind` is a free string, matching how 0023 treats `type`, so a new
accommodation kind does not need a SQLite table rebuild.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_stays (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            address TEXT,
            lat REAL,
            lon REAL,
            timezone TEXT,
            check_in_datetime TEXT NOT NULL,
            check_in_date TEXT NOT NULL,
            check_out_datetime TEXT NOT NULL,
            check_out_date TEXT NOT NULL,
            booking_reference TEXT,
            confirmation TEXT,
            contact TEXT,
            room_type TEXT,
            guests INTEGER,
            notes TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_stays_trip ON trip_stays(trip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_stays_check_in ON trip_stays(check_in_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_stays")
