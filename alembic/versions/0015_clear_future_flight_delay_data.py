"""Clear stale live delay data from future flights.

Aircraft sync was incorrectly writing delay/status data from AviationStack
(which returns the most recent past flight for a given number) onto future
bookings, causing them to show "+X min late" badges incorrectly.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """UPDATE flights
           SET live_status = NULL,
               live_departure_delay = NULL,
               live_arrival_delay = NULL,
               live_departure_actual = NULL,
               live_arrival_estimated = NULL,
               live_status_fetched_at = NULL
           WHERE departure_datetime > datetime('now', '+2 hours')
             AND (live_departure_delay IS NOT NULL OR live_arrival_delay IS NOT NULL
                  OR live_status IS NOT NULL)"""
    )


def downgrade() -> None:
    pass
