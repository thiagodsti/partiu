"""Drop last_rules_version from email_sync_state.

Parser version changes no longer trigger automatic full rescans —
full rescans are manual-only.

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_sync_state DROP COLUMN last_rules_version")


def downgrade() -> None:
    op.execute("ALTER TABLE email_sync_state ADD COLUMN last_rules_version TEXT")
