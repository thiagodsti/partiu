"""Add airport_aliases table for city-name → IATA lookups.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed data: lowercase alias → IATA code.
# These are the names used in SAS / Norwegian e-tickets and PDF itineraries.
_SEED_ALIASES: list[tuple[str, str]] = [
    ("stockholm arlanda", "ARN"),
    ("london heathrow", "LHR"),
    ("london gatwick", "LGW"),
    ("london city", "LCY"),
    ("london stansted", "STN"),
    ("london luton", "LTN"),
    ("paris charles de gaulle", "CDG"),
    ("paris orly", "ORY"),
    ("copenhagen kastrup", "CPH"),
    ("oslo gardermoen", "OSL"),
    ("oslo airport", "OSL"),
    ("oslo lufthavn", "OSL"),
    ("gothenburg landvetter", "GOT"),
    ("bergen flesland", "BGO"),
    ("helsinki vantaa", "HEL"),
    ("amsterdam schiphol", "AMS"),
    ("frankfurt", "FRA"),
    ("munich", "MUC"),
    ("zurich", "ZRH"),
    ("brussels", "BRU"),
    ("vienna", "VIE"),
    ("lisbon", "LIS"),
    ("dublin", "DUB"),
    ("madrid", "MAD"),
    ("barcelona", "BCN"),
    ("rome fiumicino", "FCO"),
    ("milan malpensa", "MXP"),
    ("milan linate", "LIN"),
    ("milan bergamo", "BGY"),
    ("bergamo", "BGY"),
    ("orio al serio", "BGY"),
    ("berlin brandenburg", "BER"),
    ("berlin tegel", "TXL"),
    ("berlin schonefeld", "SXF"),
    ("berlin schoenefeld", "SXF"),
    ("warsaw chopin", "WAW"),
    ("warsaw modlin", "WMI"),
    ("new york jfk", "JFK"),
    ("new york newark", "EWR"),
    ("los angeles", "LAX"),
    ("chicago", "ORD"),
    ("cape town", "CPT"),
    ("johannesburg", "JNB"),
    ("tokyo narita", "NRT"),
    ("tokyo haneda", "HND"),
    ("bangkok", "BKK"),
    ("singapore", "SIN"),
    ("hong kong", "HKG"),
    ("shanghai pudong", "PVG"),
    ("beijing", "PEK"),
    ("dubai", "DXB"),
    ("doha", "DOH"),
    ("istanbul", "IST"),
    # Short names used in SAS/Norwegian e-tickets
    ("arlanda", "ARN"),
    ("heathrow", "LHR"),
    ("gatwick", "LGW"),
    ("kastrup", "CPH"),
    ("gardermoen", "OSL"),
    ("landvetter", "GOT"),
    ("schiphol", "AMS"),
    ("fiumicino", "FCO"),
    ("malpensa", "MXP"),
    ("catania", "CTA"),
    ("palermo", "PMO"),
    ("alicante", "ALC"),
    ("malaga", "AGP"),
    ("tenerife", "TFS"),
    ("gran canaria", "LPA"),
    ("lanzarote", "ACE"),
    ("fuerteventura", "FUE"),
    ("ibiza", "IBZ"),
    ("majorca", "PMI"),
    ("mallorca", "PMI"),
    ("nice", "NCE"),
    ("rhodes", "RHO"),
    ("corfu", "CFU"),
    ("split", "SPU"),
    ("dubrovnik", "DBV"),
    ("krakow", "KRK"),
    ("warsaw", "WAW"),
    ("tallinn", "TLL"),
    ("riga", "RIX"),
    ("vilnius", "VNO"),
    ("edinburgh", "EDI"),
    ("manchester", "MAN"),
    ("birmingham", "BHX"),
    ("bristol", "BRS"),
    ("stansted", "STN"),
    ("luton", "LTN"),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS airport_aliases (
            alias     TEXT PRIMARY KEY,
            iata_code TEXT NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_airport_aliases_iata ON airport_aliases(iata_code)")

    for alias, iata in _SEED_ALIASES:
        safe_alias = alias.replace("'", "''")
        op.execute(
            f"INSERT OR IGNORE INTO airport_aliases (alias, iata_code) VALUES ('{safe_alias}', '{iata}')"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS airport_aliases")
