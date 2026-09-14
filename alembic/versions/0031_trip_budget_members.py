"""Who a budget is shared with.

A budget was already keyed on (trip_id, user_id) — one per person, because what
a trip costs *you* is not what it costs your companion. That stays true, and
this table says who "you" is: a budget can name several people, and then its
spend is the **sum of their shares**. Two people travelling together on one
purse is the common case, and splitting every expense between them only to
watch two half-budgets fill in lockstep told them nothing.

Members are `(type, id)` exactly like expense participants, so a companion with
no Partiu account can be one through `guests` — which is the whole reason guests
exist. The owner is stored as a member row like anyone else rather than being
implied, so the share SQL is one uniform join instead of a join plus a special
case.

A budget resolves for a person as: their own first, else one that names them.
That is what lets both halves of a couple open the trip and see the same bar.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_budget_members (
            trip_id TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL,
            member_type TEXT NOT NULL CHECK (member_type IN ('user', 'guest')),
            member_id INTEGER NOT NULL,
            PRIMARY KEY (trip_id, owner_user_id, member_type, member_id),
            FOREIGN KEY (trip_id, owner_user_id)
                REFERENCES trip_budgets(trip_id, user_id) ON DELETE CASCADE
        )
    """)
    # Resolution reads this the other way round — "which budget names me?" —
    # so the primary key's leading columns are the wrong order for it.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_budget_members_member "
        "ON trip_budget_members(trip_id, member_type, member_id)"
    )
    # Every budget that already exists is a budget for exactly its owner.
    op.execute("""
        INSERT OR IGNORE INTO trip_budget_members (trip_id, owner_user_id, member_type, member_id)
        SELECT trip_id, user_id, 'user', user_id FROM trip_budgets
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_budget_members_member")
    op.execute("DROP TABLE IF EXISTS trip_budget_members")
