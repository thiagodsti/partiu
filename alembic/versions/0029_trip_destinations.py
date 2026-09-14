"""A trip goes to more than one place.

0027 gave a trip a typed origin and a typed destination, one each. The origin is
genuinely one place — a trip starts where you start — but the far end is not: a
fortnight in Brazil is São Paulo *and* Rio, and naming only the first makes the
others invisible to the card, to the cover photo, and to the visited-countries
count.

So destinations become their own ordered table, the shape `trip_segments` and
`trip_stays` already use, and each row carries its own coordinates and country
code. A row per place is what lets every destination count as a country visited;
a JSON list on `trips` would have made that a string-parsing exercise in SQL.

The single `destination_*` columns from 0027 are backfilled into the table and
then dropped. Keeping them as a mirror of "the first one" would be two sources
of truth for the same fact, which is how the derived/declared confusion started
in the first place. `destination_airport` is untouched — that one is derived
from the flights and answers a different question.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_destinations (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            lat REAL,
            lon REAL,
            country_code TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_destinations_trip "
        "ON trip_destinations(trip_id, sort_order)"
    )

    # Carry the single destination over. `hex(randomblob(16))` gives each row an
    # id without needing a Python pass over the table.
    op.execute("""
        INSERT INTO trip_destinations (id, trip_id, name, lat, lon, country_code, sort_order, created_at)
        SELECT lower(hex(randomblob(16))), id, destination_place, destination_lat,
               destination_lon, destination_country, 0,
               COALESCE(updated_at, created_at, datetime('now'))
        FROM trips
        WHERE destination_place IS NOT NULL AND TRIM(destination_place) != ''
    """)

    for column in (
        "destination_place",
        "destination_lat",
        "destination_lon",
        "destination_country",
    ):
        op.execute(f"ALTER TABLE trips DROP COLUMN {column}")


def downgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN destination_place TEXT")
    op.execute("ALTER TABLE trips ADD COLUMN destination_lat REAL")
    op.execute("ALTER TABLE trips ADD COLUMN destination_lon REAL")
    op.execute("ALTER TABLE trips ADD COLUMN destination_country TEXT")
    # Only the first destination fits back; the rest cannot be represented.
    op.execute("""
        UPDATE trips SET
            destination_place = (
                SELECT name FROM trip_destinations d WHERE d.trip_id = trips.id
                ORDER BY sort_order LIMIT 1
            ),
            destination_lat = (
                SELECT lat FROM trip_destinations d WHERE d.trip_id = trips.id
                ORDER BY sort_order LIMIT 1
            ),
            destination_lon = (
                SELECT lon FROM trip_destinations d WHERE d.trip_id = trips.id
                ORDER BY sort_order LIMIT 1
            ),
            destination_country = (
                SELECT country_code FROM trip_destinations d WHERE d.trip_id = trips.id
                ORDER BY sort_order LIMIT 1
            )
    """)
    op.execute("DROP TABLE IF EXISTS trip_destinations")
