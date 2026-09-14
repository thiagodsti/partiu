"""A budget for a trip — one per person, not one per trip.

A trip can be shared, and what it costs *you* is not what it costs your
companion: you may have booked the flights and they the hotel, and you may not
even be spending to the same limit. So the row is keyed on (trip_id, user_id)
and a collaborator sets their own.

`amount` is stored with its `currency` rather than in some base unit, because
this app has no exchange rates and will not invent any. Expenses in the budget's
currency count against it; spend in any other currency is reported alongside and
never folded in — a converted figure would be a guess presented as a fact, which
is the one thing the parsing side of this codebase refuses to do too.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_budgets (
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount REAL NOT NULL,
            currency TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trip_id, user_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_budgets")
