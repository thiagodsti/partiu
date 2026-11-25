"""Drop the blocked-sender list (non_flight_domains).

The list predates every structural reader. It was added in 0010 to stop a
proximity-guessing parser from inventing flights out of hotel and restaurant
mail. That parser is gone (see AGENTS.md, "No generic extraction tier"), and
what is left either decides for itself whether it applies (airline rules are
sender-gated, the GDS and schema.org readers need their own markers) or ran
ahead of the skip anyway (lodging, car rentals). The one reader the list still
shielded was the LLM fallback, and it is now gated on the email's own content
(`parsers/booking_signal.may_describe_a_flight`), which also covers senders no
one had added.

Measured on the 372-email corpus: with the list gone and the content gate in
place, the LLM is offered 61 mails where the list let 192 through, while 88 of
the 90 real flight bookings still pass the gate.

Downgrade recreates the empty table; the entries are not restored.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS non_flight_domains")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS non_flight_domains (
            domain      TEXT PRIMARY KEY,
            note        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
