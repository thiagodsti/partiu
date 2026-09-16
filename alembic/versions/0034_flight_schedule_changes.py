"""Remember that an airline moved a flight, and what it moved it from.

`_process_emails` has always let a newer itinerary mail overwrite a stored
leg's times ("newer email wins"). That is the right data, silently: nothing
recorded that the change happened, no one was told, and a leg moved to a
*different day* did not match the number-plus-date lookup at all, so it was
created beside the old one.

Two facts, two column sets:

* `rescheduled_from_departure` / `rescheduled_from_arrival` / `rescheduled_at`
  — the times the leg had immediately before the last change and when it was
  applied. Previous, not original: a notification reports the move that just
  happened, and the row keeps the same answer it gave.
* `schedule_change_notice_at` — an airline announced a change to this booking
  without printing the new itinerary (SAS does exactly this). Nothing on the
  row can be updated from such a mail; the traveller can only be pointed at it.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE flights ADD COLUMN rescheduled_from_departure TEXT")
    op.execute("ALTER TABLE flights ADD COLUMN rescheduled_from_arrival TEXT")
    op.execute("ALTER TABLE flights ADD COLUMN rescheduled_at TEXT")
    op.execute("ALTER TABLE flights ADD COLUMN schedule_change_notice_at TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE flights DROP COLUMN rescheduled_from_departure")
    op.execute("ALTER TABLE flights DROP COLUMN rescheduled_from_arrival")
    op.execute("ALTER TABLE flights DROP COLUMN rescheduled_at")
    op.execute("ALTER TABLE flights DROP COLUMN schedule_change_notice_at")
