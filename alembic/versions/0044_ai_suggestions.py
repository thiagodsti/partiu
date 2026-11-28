"""AI place suggestions in the planner: a per-user preference and a daily count.

``ai_suggestion_prefs`` holds whether a traveller lets the suggestions read
their past trips (ratings and trip notes). Off unless they turn it on, because
those notes are free text and go to an outside AI provider.

``ai_suggestion_usage`` counts requests per user per UTC day, so one account
cannot run up the provider bill; the limit is ``AI_SUGGESTIONS_DAILY_LIMIT``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_suggestion_prefs (
            user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            use_history INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_suggestion_usage (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day     TEXT NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_suggestion_usage")
    op.execute("DROP TABLE IF EXISTS ai_suggestion_prefs")
