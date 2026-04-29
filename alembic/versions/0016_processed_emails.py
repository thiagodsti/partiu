"""Add processed_emails table to prevent re-importing deleted trips.

Tracks email message IDs that have been successfully processed per user,
so deleted flights/trips are not re-created on the next sync.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email_message_id TEXT NOT NULL,
            processed_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, email_message_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_processed_emails_user ON processed_emails(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS processed_emails")
