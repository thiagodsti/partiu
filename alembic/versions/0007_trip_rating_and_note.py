"""Add shared rating and note columns to trips.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Shared 1–5 star rating (owner or any shared user can update)
    op.execute("ALTER TABLE trips ADD COLUMN rating INTEGER DEFAULT NULL")
    # Shared free-text note (editable by owner or any shared user)
    op.execute("ALTER TABLE trips ADD COLUMN note TEXT DEFAULT NULL")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN — nothing to do
    pass
