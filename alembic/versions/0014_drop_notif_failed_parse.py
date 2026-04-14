"""Drop unused notif_failed_parse column from users.

The failed-parse notification type was never implemented — the column
has no references in application code or the frontend.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN notif_failed_parse")


def downgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN notif_failed_parse INTEGER NOT NULL DEFAULT 1")
