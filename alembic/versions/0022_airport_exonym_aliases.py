"""Curated exonym / local-name airport aliases.

Airport reference data stores one name per airport, but itineraries use whichever
name the issuing system prefers: "Wien" or "Vienna", "Praha" or "Prague",
"Firenze" or "Florence".  Accent folding cannot bridge those, and the CSV's
`keywords` column only covers some of them — and where it does, it can point at
the wrong airport (Warsaw *Modlin* lists "Warszawa"; WAW does not).

These entries are curated, so they are written with OR REPLACE to take
precedence over the keyword-derived aliases seeded at startup by
``AirportRepository.seed_aliases_from_keywords``.

Each maps to the airport a scheduled itinerary means by default when the city
alone is named.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# lowercase, accent-folded alias → IATA code
_EXONYMS: list[tuple[str, str]] = [
    # German-speaking
    ("wien", "VIE"),
    ("muenchen", "MUC"),
    ("munchen", "MUC"),
    ("koeln", "CGN"),
    ("nurnberg", "NUE"),
    ("nuernberg", "NUE"),
    ("genf", "GVA"),
    ("zuerich", "ZRH"),
    # Nordic
    # "copenhagen" is claimed by Roskilde ("Copenhagen Airport, Roskilde") in the
    # CSV keywords; the same trap catches Sydney (Nova Scotia) further below.
    ("copenhagen", "CPH"),
    ("kobenhavn", "CPH"),
    ("koebenhavn", "CPH"),
    ("kopenhamn", "CPH"),
    ("goteborg", "GOT"),
    ("gothenburg", "GOT"),
    ("reykjavik", "KEF"),
    # Romance
    ("firenze", "FLR"),
    ("florence", "FLR"),
    ("torino", "TRN"),
    ("turin", "TRN"),
    ("genova", "GOA"),
    ("venezia", "VCE"),
    ("napoli", "NAP"),
    ("milano", "MXP"),
    ("roma", "FCO"),
    ("lisboa", "LIS"),
    ("sevilla", "SVQ"),
    ("geneve", "GVA"),
    ("marseilles", "MRS"),
    # Central & Eastern Europe
    ("praha", "PRG"),
    ("warszawa", "WAW"),
    ("warsaw", "WAW"),
    ("bucuresti", "OTP"),
    ("bucharest", "OTP"),
    ("beograd", "BEG"),
    ("moskva", "SVO"),
    ("kyiv", "KBP"),
    ("kiev", "KBP"),
    # Low Countries
    ("antwerpen", "ANR"),
    ("den haag", "AMS"),
    ("bruxelles", "BRU"),
    ("brussel", "BRU"),
    # Elsewhere — same "small namesake claims the keyword" problem
    ("sydney", "SYD"),
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
