"""Add trip_day_notes table for trip day planner feature.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_day_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(trip_id, date)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_day_notes_trip_id ON trip_day_notes(trip_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_trip_day_notes_trip_id")
    op.execute("DROP TABLE IF EXISTS trip_day_notes")
