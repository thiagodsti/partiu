"""Which guests are on which trip, stated rather than inferred.

Guest membership used to be **derived**: `GuestRepository.list_for_trip` asked
which guests some expense on this trip already names. That kept a guest from one
trip out of an unrelated trip's picker, which was the right goal — but it made
the roster a consequence of the expenses instead of a fact about the trip, and
the two are not the same thing. The visible cost was a dead end: a guest created
in Settings appeared in no picker, because no expense named them yet, and no
expense could name them because they were in no picker. Three guests were added
on a real install and none could be used.

So the roster is its own table. A trip says who is on it; the expense form then
offers exactly those people, their names are picked from a list bounded by the
trip, and a trip nobody was added to offers only its owner and collaborators.

The backfill preserves every existing arrangement exactly: whoever the old
derived query would have returned becomes a stated member. Nothing an install
already has changes shape, and `list_for_trip`'s answer is identical the moment
after this migration runs as it was the moment before.

Deliberately **not** carrying an `added_by`: a guest belongs to the trip, not to
whoever typed them in, and any collaborator can manage the roster for the same
reason any of them can add an expense.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_guests (
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            guest_id INTEGER NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (trip_id, guest_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_guests_trip_id ON trip_guests(trip_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trip_guests_guest_id ON trip_guests(guest_id)")

    # Backfill from the old derived rule — the union of guests named as a
    # participant or as the payer on any of the trip's expenses — so the roster
    # starts out saying exactly what the derivation would have said.
    op.execute("""
        INSERT OR IGNORE INTO trip_guests (trip_id, guest_id)
        SELECT e.trip_id, p.guest_id
        FROM trip_expense_participants p
        JOIN trip_expenses e ON e.id = p.expense_id
        WHERE p.guest_id IS NOT NULL
    """)
    op.execute("""
        INSERT OR IGNORE INTO trip_guests (trip_id, guest_id)
        SELECT trip_id, paid_by_guest_id
        FROM trip_expenses
        WHERE paid_by_guest_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_guests")
