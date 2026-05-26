"""Per-user Immich album storage for shared trips.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_immich_albums (
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            album_id TEXT NOT NULL,
            PRIMARY KEY (trip_id, user_id)
        )
    """)
    # Migrate existing albums — the stored album was always created by the trip owner
    op.execute("""
        INSERT OR IGNORE INTO trip_immich_albums (trip_id, user_id, album_id)
        SELECT id, user_id, immich_album_id
        FROM trips
        WHERE immich_album_id IS NOT NULL
    """)
    # Drop the now-redundant column (requires SQLite >= 3.35, shipped with Python 3.12+)
    op.execute("ALTER TABLE trips DROP COLUMN immich_album_id")


def downgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN immich_album_id TEXT")
    op.execute("""
        UPDATE trips SET immich_album_id = (
            SELECT album_id FROM trip_immich_albums
            WHERE trip_immich_albums.trip_id = trips.id
              AND trip_immich_albums.user_id = trips.user_id
            LIMIT 1
        )
    """)
    op.execute("DROP TABLE IF EXISTS trip_immich_albums")
