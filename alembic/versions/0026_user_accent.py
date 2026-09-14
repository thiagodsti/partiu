"""Store the chosen accent colour on the user, not in the browser.

The accent (and the light/dark theme) started out in localStorage. That makes a
colour a property of *a browser*, which is wrong for the accent in two ways:
two people sharing one browser overwrite each other's choice, and one person
with a phone and a laptop gets a different-looking app on each.

The theme deliberately stays local — wanting dark on a phone at night and light
on a desktop is a real preference, and it is about the device's surroundings.
The accent is about the person, so it lives next to `locale`, which is the same
kind of per-user display preference and is already carried on /api/auth/me.

`sky` is the default rather than NULL so every existing row answers the question
without the frontend having to treat "unset" as a third state.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN accent TEXT NOT NULL DEFAULT 'sky'")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN accent")
