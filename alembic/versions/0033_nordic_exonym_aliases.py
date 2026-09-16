"""Nordic exonym airport aliases.

Norwegian and SAS write their Swedish-language itineraries with Swedish place
names: "Helsingfors" for Helsinki, "Lissabon" for Lisbon, "Aten" for Athens.
None of these is in the reference CSV's keywords, so ``resolve_iata`` returned
'' and the leg was dropped — three Norwegian bookings in the measured corpus
lost their Helsinki legs this way while the Copenhagen ones ("Köpenhamn", which
0022 already covers) came through.

Same shape and precedence as 0022: curated, written with OR REPLACE so they
outrank the keyword-derived aliases seeded at startup.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# lowercase, accent-folded alias → IATA code
_EXONYMS: list[tuple[str, str]] = [
    # Swedish
    ("helsingfors", "HEL"),
    ("lissabon", "LIS"),
    ("aten", "ATH"),
    ("bryssel", "BRU"),
    ("prag", "PRG"),
    ("venedig", "VCE"),
    ("nizza", "NCE"),
    ("neapel", "NAP"),
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS airport_aliases ("
        "alias TEXT PRIMARY KEY, iata_code TEXT NOT NULL)"
    )
    for alias, iata in _EXONYMS:
        conn.exec_driver_sql(
            "INSERT OR REPLACE INTO airport_aliases (alias, iata_code) VALUES (?, ?)",
            (alias, iata),
        )


def downgrade() -> None:
    conn = op.get_bind()
    for alias, _ in _EXONYMS:
        conn.exec_driver_sql("DELETE FROM airport_aliases WHERE alias = ?", (alias,))
