"""Record the country of each stored place, for the visited-countries statistic.

Travel statistics counted countries by joining `flights` to `airports.country_code`.
A station and a hotel have no IATA code to join on, so a Stockholm-Oslo train
proved nothing and Norway went uncounted.

The country is **recorded, never inferred**. It comes from the `countrycode` the
geocoder returned for the result the user actually picked, which is OSM boundary
data. Deriving it from the stored coordinates instead was measured first — using
the nearest airport in the local `airports` table — and it put Malmö Central in
Denmark, because Copenhagen's airport is closer to it than any Swedish one.
Border cities are exactly where a rail trip is most likely to cross a frontier,
so that is the worst place to be wrong, and a wrong country shown as a visited
fact is worse than a missing one.

Rows written before this migration have coordinates but no country. They are
backfilled from Photon's /reverse endpoint by `backfill_place_countries()`, run
once at startup and flagged in `global_settings` — the same pattern the airport
rank backfill uses. Where Photon is unconfigured or unreachable the column stays
NULL and the place simply does not contribute a country.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trip_segments ADD COLUMN departure_country TEXT")
    op.execute("ALTER TABLE trip_segments ADD COLUMN arrival_country TEXT")
    op.execute("ALTER TABLE trip_stays ADD COLUMN country TEXT")


def downgrade() -> None:
    # SQLite gained DROP COLUMN in 3.35; these are all nullable and unindexed.
    op.execute("ALTER TABLE trip_segments DROP COLUMN departure_country")
    op.execute("ALTER TABLE trip_segments DROP COLUMN arrival_country")
    op.execute("ALTER TABLE trip_stays DROP COLUMN country")
