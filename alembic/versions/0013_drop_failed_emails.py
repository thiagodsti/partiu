"""Drop failed_emails table.

The failed-email queue feature was removed; the table is no longer
written to or read from anywhere in the application.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS failed_emails")


def downgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS failed_emails (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            subject TEXT NOT NULL,
            received_at TEXT,
            reason TEXT NOT NULL,
            airline_hint TEXT NOT NULL DEFAULT '',
            eml_path TEXT,
            last_retried_at TEXT,
            parser_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            llm_verdict TEXT DEFAULT NULL
        )"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_failed_emails_user_id ON failed_emails(user_id)")
