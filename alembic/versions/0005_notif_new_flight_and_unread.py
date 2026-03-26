"""Add new_flight/failed_parse notification prefs and unread badge counter.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN notif_new_flight INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE users ADD COLUMN notif_failed_parse INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE users ADD COLUMN notif_unread INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN on all versions — leave as-is
    pass
