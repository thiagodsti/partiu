"""Booking emails nothing could read, offered for review.

``email_candidates`` holds a mail the sync could not import but that looks like
a flight booking (``parsers/booking_signal.looks_like_flight_booking``), with
its text trimmed to what the review page and the LLM draft need, and what was
detected in it (flight numbers, airport codes, dates, times, booking code).
The text is cleared once the traveller imports or dismisses the mail: keeping
an email's contents only as long as there is a decision to make.

``email_review_ignored_senders`` is the per-user "never show mail from this
sender again" list, keyed on the sender's domain.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_candidates (
            id                 TEXT PRIMARY KEY,
            user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message_id         TEXT NOT NULL,
            sender             TEXT,
            subject            TEXT,
            email_date         TEXT,
            body_text          TEXT,
            hints              TEXT NOT NULL DEFAULT '{}',
            booking_reference  TEXT,
            status             TEXT NOT NULL DEFAULT 'pending',
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            UNIQUE (user_id, message_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_candidates_user_status "
        "ON email_candidates(user_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_review_ignored_senders (
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            domain      TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (user_id, domain)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_review_ignored_senders")
    op.execute("DROP TABLE IF EXISTS email_candidates")
