"""Add airport ranking (type / scheduled_service) and accent-folded search columns.

`type` and `scheduled_service` already exist in the OurAirports CSV but were
never imported, so name resolution had no way to tell a large international
airport apart from a heliport or a disused airstrip that happened to share a
city name — "Faro" resolved to a small Canadian field over Faro (Portugal),
"Helsinki" to a heliport.  Ranking on these columns is what makes city-name
resolution safe.

`name_folded` / `city_folded` hold accent-stripped lowercase copies, because
SQLite's LIKE is accent-sensitive: "Dusseldorf" could never match "Düsseldorf"
and "Florianopolis" never matched "Florianópolis".

Existing databases are backfilled by ``AirportRepository.backfill_rank_columns``
at startup; a NULL type simply scores neutral until then.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(conn, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.exec_driver_sql(f"PRAGMA table_info({table})"))


def upgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "airports", "type"):
        op.execute("ALTER TABLE airports ADD COLUMN type TEXT")
    if not _has_column(conn, "airports", "scheduled_service"):
        op.execute("ALTER TABLE airports ADD COLUMN scheduled_service INTEGER NOT NULL DEFAULT 0")
    if not _has_column(conn, "airports", "name_folded"):
        op.execute("ALTER TABLE airports ADD COLUMN name_folded TEXT")
    if not _has_column(conn, "airports", "city_folded"):
        op.execute("ALTER TABLE airports ADD COLUMN city_folded TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_airports_name_folded ON airports(name_folded)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_airports_city_folded ON airports(city_folded)")


def downgrade() -> None:
    # SQLite pre-3.35 cannot DROP COLUMN; leaving the columns in place is a
    # harmless no-op for older revisions of the schema.
    pass
