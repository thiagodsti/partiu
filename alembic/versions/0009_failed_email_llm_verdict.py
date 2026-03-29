"""Add llm_verdict column to failed_emails.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 'no_flight' = LLM explicitly said no flight here; NULL = not yet tried
    op.execute("ALTER TABLE failed_emails ADD COLUMN llm_verdict TEXT DEFAULT NULL")


def downgrade() -> None:
    pass
