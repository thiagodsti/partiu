"""Known flight routes, for checking what the LLM fallback reads.

Small local models read the right airports but sometimes in the wrong order
(an Azul VCP→FLN confirmation comes back as FLN→VCP every time), and an
inverted route passes every validation gate. Virtual Radar Server's standing
data (CC0, https://github.com/vradarserver/standing-data) lists the airports
each callsign flies, in order; with it, a leg whose route is the exact reverse
of the known one can be put back the right way round.

`flight_routes` is keyed on the ICAO callsign (`DLH400`) and keeps the ICAO
airport codes as published (`EDDF-KJFK`); `airline_icao` maps IATA airline
codes to ICAO ones, one row per pair, since an IATA code can be shared.
Both are replaced wholesale on every refresh (integrations/routes/).

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS flight_routes (
            callsign TEXT PRIMARY KEY,
            airports TEXT NOT NULL
        ) WITHOUT ROWID
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS airline_icao (
            iata TEXT NOT NULL,
            icao TEXT NOT NULL,
            PRIMARY KEY (iata, icao)
        ) WITHOUT ROWID
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS flight_routes")
    op.execute("DROP TABLE IF EXISTS airline_icao")
