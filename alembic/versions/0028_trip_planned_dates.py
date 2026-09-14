"""Remember the span the traveller declared, not only the one their legs imply.

`trips.start_date` / `end_date` are **derived**: `_recompute_span` recomputes
them as MIN/MAX over the trip's flights, segments and stays. That is right for
what they are, and it has one consequence that only shows up once something
tries to *use* the span: a trip created by hand with dates 30 Dec – 2 Jan has
exactly those dates until its first leg is added, at which point the span
collapses to that one leg's day. Adding the return leg next would then fall
outside the trip's own dates.

So the typed pair gets its own columns, and `_recompute_span` unions them in.
The derived span can then only ever *grow* past what was declared, never shrink
inside it, which is what makes it safe to bound a date picker with — and the
declared dates stay editable, so the span still shrinks when the traveller says
so rather than when a leg happens to be deleted.

Same split, and the same reason, as migration 0027's place columns: a derived
value and a stated one are two different facts about a trip.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN planned_start_date TEXT")
    op.execute("ALTER TABLE trips ADD COLUMN planned_end_date TEXT")
    # Existing manually-created trips already carry the dates their owner typed
    # (nothing has recomputed them away yet if they have no legs); adopt them so
    # an upgrade does not silently forget a declared span.
    op.execute(
        """UPDATE trips
           SET planned_start_date = start_date,
               planned_end_date = end_date
           WHERE is_auto_generated = 0
             AND start_date IS NOT NULL
             AND end_date IS NOT NULL"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trips DROP COLUMN planned_start_date")
    op.execute("ALTER TABLE trips DROP COLUMN planned_end_date")
