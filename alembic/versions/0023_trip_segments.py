"""Add trip_segments — manually-added non-flight transport legs (train, bus, ferry, car).

Deliberately a separate table from `flights` rather than a `transport_type`
discriminator on it. `flights` carries ~15 flight-only columns (aircraft, live
status, BCBP linkage, email_message_id) and ten backend modules query it
directly; a discriminator would need a `WHERE type = 'flight'` guard at every
one of those call sites, and the first missed guard feeds a bus into the
aircraft-type sync job.

Places are stored as a free-text label plus optional coordinates rather than an
airport IATA code — train and bus stations are not in the `airports` table, and
the coordinates come from the geocoder (see backend/integrations/photon/).
Coordinates are nullable so a segment typed by hand, with no geocoder match,
still saves; it just gets no map line and no timezone conversion.

`type` is a free string rather than a CHECK constraint so accommodation
('stay') can join later without a table rebuild — SQLite cannot alter a CHECK.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_segments (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            operator TEXT,
            number TEXT,
            booking_reference TEXT,
            departure_place TEXT NOT NULL,
            departure_lat REAL,
            departure_lon REAL,
            departure_datetime TEXT NOT NULL,
            departure_timezone TEXT,
            arrival_place TEXT NOT NULL,
            arrival_lat REAL,
            arrival_lon REAL,
            arrival_datetime TEXT NOT NULL,
            arrival_timezone TEXT,
            seat TEXT,
            notes TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_segments_trip ON trip_segments(trip_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_segments_departure "
        "ON trip_segments(departure_datetime)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_segments")
