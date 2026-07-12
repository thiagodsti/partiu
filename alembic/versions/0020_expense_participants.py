"""Add guests, expense paid_by and expense participants (equal-split tagging).

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS guests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_guests_owner ON guests(owner_id)")

    op.execute("ALTER TABLE trip_expenses ADD COLUMN paid_by_user_id INTEGER")
    op.execute("ALTER TABLE trip_expenses ADD COLUMN paid_by_guest_id INTEGER")
    op.execute(
        "UPDATE trip_expenses SET paid_by_user_id = created_by WHERE paid_by_user_id IS NULL"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_expense_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_id TEXT NOT NULL REFERENCES trip_expenses(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            guest_id INTEGER REFERENCES guests(id) ON DELETE CASCADE,
            CHECK ((user_id IS NULL) != (guest_id IS NULL))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_expense_participants_expense "
        "ON trip_expense_participants(expense_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_expense_participants")
    op.execute("ALTER TABLE trip_expenses DROP COLUMN paid_by_guest_id")
    op.execute("ALTER TABLE trip_expenses DROP COLUMN paid_by_user_id")
    op.execute("DROP TABLE IF EXISTS guests")
