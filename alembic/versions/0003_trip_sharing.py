"""Add trip_shares and trusted_users tables for trip sharing feature.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            invited_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(trip_id, user_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_shares_trip_id ON trip_shares(trip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_shares_user_id ON trip_shares(user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS trusted_users (
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            trusted_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (owner_id, trusted_user_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trusted_users")
    op.execute("DROP TABLE IF EXISTS trip_shares")
