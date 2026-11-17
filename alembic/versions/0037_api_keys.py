"""Personal API keys, created on demand from Settings.

Until now the only credential the API accepted was the browser's session
cookie, so nothing outside the SPA — a script, a home dashboard, another
self-hosted service — could read a trip without scraping a login. A key is a
long random secret the holder sends as `Authorization: Bearer partiu_…`.

Nothing is generated at startup or at account creation: a key exists only
because someone pressed the button, which is also the only moment its value is
ever shown. Only a SHA-256 of it is stored — the secret is 256 random bits, so a
slow password hash would buy nothing — next to a short `prefix` that lets the
list say which key is which without holding anything usable.

`scope` is `read` (GET/HEAD only) or `write` (everything a key may do at all);
see `api_keys/service.py` for the surfaces no key can reach whatever its scope.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            prefix TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            scope TEXT NOT NULL CHECK (scope IN ('read', 'write')),
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            expires_at TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_keys")
