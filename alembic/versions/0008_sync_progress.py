"""Add emails_processed and emails_total to email_sync_state.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_sync_state ADD COLUMN emails_processed INTEGER DEFAULT 0")
    op.execute("ALTER TABLE email_sync_state ADD COLUMN emails_total INTEGER DEFAULT 0")


def downgrade() -> None:
    pass
