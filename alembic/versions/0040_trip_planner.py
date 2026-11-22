"""The trip organizer: a route of cities, a plan per day, and a to-do list.

Planning a trip before (or while) booking it needs three things the imported
data does not give: **where you will be each night** before any hotel is
booked (`trip_plan_stops`, an ordered route of cities with arrival and
departure dates), **what you mean to do each day** as separate, movable items
rather than one free-text note (`trip_plan_items`; a NULL `date` is an idea not
yet placed on a day), and **what must be done before leaving**, with who is
doing it (`trip_plan_tasks`; the assignee is a trip participant, a user or a
guest, as on expenses).

Imported flights, ground legs and stays are not copied here: the organizer
reads them where they live, so a booking that arrives by mail shows up on the
board without a second source of truth.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_plan_stops (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            lat REAL,
            lon REAL,
            country_code TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            notes TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_plan_stops_trip ON trip_plan_stops(trip_id, start_date)"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_plan_items (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            date TEXT,
            time TEXT,
            title TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'idea',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_plan_items_trip ON trip_plan_items(trip_id, date, sort_order)"
    )
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_plan_tasks (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            done INTEGER NOT NULL DEFAULT 0,
            assignee_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            assignee_guest_id INTEGER REFERENCES guests(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_plan_tasks_trip ON trip_plan_tasks(trip_id, sort_order)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_plan_tasks")
    op.execute("DROP TABLE IF EXISTS trip_plan_items")
    op.execute("DROP TABLE IF EXISTS trip_plan_stops")
