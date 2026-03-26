"""Add notifications inbox table for in-app notification center.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '/',
            read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, read)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_notifications_user_read")
    op.execute("DROP INDEX IF EXISTS idx_notifications_user_id")
    op.execute("DROP TABLE IF EXISTS notifications")
