"""Add trip_expenses table and default_currency to users.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_expenses (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'EUR',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_expenses_trip ON trip_expenses(trip_id)")
    op.execute("ALTER TABLE users ADD COLUMN default_currency TEXT NOT NULL DEFAULT 'EUR'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_expenses")
