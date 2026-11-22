"""Record the price a booking mail states on the stay it imported.

The importer turns a confirmation's total into a trip expense. `price_amount`
and `price_currency` are what the mail said, written once, and they double as
the marker that the expense was made: a stay imported before prices were read
gets its expense the next time its mail is parsed (a rescan), and one whose
expense the traveller deleted does not get it back, because its price is
already recorded. Nullable: hand-entered stays and Airbnb bookings carry none.

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trip_stays ADD COLUMN price_amount REAL")
    op.execute("ALTER TABLE trip_stays ADD COLUMN price_currency TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE trip_stays DROP COLUMN price_amount")
    op.execute("ALTER TABLE trip_stays DROP COLUMN price_currency")
