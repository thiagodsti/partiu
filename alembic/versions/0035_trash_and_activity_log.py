"""A trash for deleted trips and flights, and a log of what was done to them.

Deleting a trip used to run `DELETE FROM flights … ; DELETE FROM trips …` and
that was the end of it: no record that it happened, no way back, and — because
the mails behind those flights stayed in the processed-mail ledger — no way for
a sync to bring them back either. A trip with a rating, notes and expenses on it
vanished from a real install and nothing could say when or how.

`trash` holds a JSON snapshot of the deleted row and every row reachable from
it through foreign keys (flights, boarding passes, notes, expenses and their
participants, stays, segments, rentals, documents, shares, budgets…), taken by
walking the schema rather than a hand-kept list, so a table added later is
included without anyone remembering to. The live rows are still deleted: every
query in the app keeps working unchanged, and — the point of a delete in this
app — the source mail's unique key is free again, so a mis-parsed booking can be
deleted and re-imported with a better parser.

`activity_log` is the history the trash implies: deletions, restores, permanent
deletes, merges, regroups and full syncs, per user, with enough detail to answer
"what happened to my Reykjavík trip".

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The version a user last synced under. The column was designed in with the
    # baseline schema and lost when the table was rebuilt; nothing ever wrote
    # it, which is why the rescan a version bump promised never happened.
    conn = op.get_bind()
    columns = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(email_sync_state)")}
    if "parser_version" not in columns:
        op.execute(
            "ALTER TABLE email_sync_state ADD COLUMN parser_version TEXT NOT NULL DEFAULT ''"
        )
    op.execute(
        """CREATE TABLE IF NOT EXISTS trash (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            label TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            deleted_at TEXT NOT NULL
        )"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_trash_user ON trash(user_id, deleted_at)")
    op.execute(
        """CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            label TEXT,
            details TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_activity_user ON activity_log(user_id, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS activity_log")
    op.execute("DROP TABLE IF EXISTS trash")
    op.execute("ALTER TABLE email_sync_state DROP COLUMN parser_version")
