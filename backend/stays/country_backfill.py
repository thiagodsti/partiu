"""One-time backfill of the country column on places stored before it existed.

Segments and stays written before migration 0025 carry coordinates but no
country, so they contribute nothing to the visited-countries statistic. This
resolves them through Photon's /reverse endpoint — a real boundary lookup, not
an inference. Deriving the country from the nearest airport in the local
`airports` table was measured first and put Malmö Central in Denmark, which is
precisely the kind of border city a rail trip crosses.

Design constraints this shape comes from:

* Photon is **optional**. With no geocoder configured the backfill does not run
  at all and the flag is not set, so an instance that later configures one picks
  the work up on its next start. Same reasoning as the airport rank backfill,
  which only records completion when the CSV pass actually ran.
* It is **network-bound and rate-limited** by a public service, so it runs in a
  background thread at startup rather than blocking it, sleeps between calls,
  and stops after a bounded number of rows per run.
* A row that resolves to nothing is left NULL and retried on a later run. A
  place with no coordinates can never resolve and is skipped without cost.
"""

import logging
import threading
import time

from ..database import db_conn, db_write, get_global_setting, set_global_setting
from ..integrations.photon import client as photon

logger = logging.getLogger(__name__)

_FLAG = "place_country_backfill_done"

# Courtesy pause between calls — the default Photon endpoint is a free public
# service, and this is bulk work nobody is waiting on.
_DELAY_SECONDS = 1.0

# Bounded per run so a large history cannot hold a thread for hours; whatever is
# left is picked up next start, because the flag is only set on a clean sweep.
_MAX_PER_RUN = 200


def _pending() -> list[tuple[str, str, str, float, float]]:
    """(table, id_column_value, column, lat, lon) for every unresolved place."""
    with db_conn() as conn:
        rows: list[tuple[str, str, str, float, float]] = []
        for sql, column in (
            (
                "SELECT id, departure_lat AS lat, departure_lon AS lon FROM trip_segments "
                "WHERE departure_country IS NULL AND departure_lat IS NOT NULL",
                "departure_country",
            ),
            (
                "SELECT id, arrival_lat AS lat, arrival_lon AS lon FROM trip_segments "
                "WHERE arrival_country IS NULL AND arrival_lat IS NOT NULL",
                "arrival_country",
            ),
            (
                "SELECT id, lat, lon FROM trip_stays WHERE country IS NULL AND lat IS NOT NULL",
                "country",
            ),
        ):
            table = "trip_stays" if column == "country" else "trip_segments"
            rows.extend(
                (table, r["id"], column, r["lat"], r["lon"]) for r in conn.execute(sql).fetchall()
            )
    return rows


def backfill_place_countries() -> int:
    """Resolve and store missing country codes. Returns how many were written."""
    if get_global_setting(_FLAG) == "1":
        return 0
    if not photon.is_configured():
        logger.info("Place country backfill skipped — no geocoder configured")
        return 0

    pending = _pending()
    if not pending:
        set_global_setting(_FLAG, "1")
        return 0

    logger.info("Place country backfill: %d place(s) to resolve", len(pending))
    written = 0
    for table, row_id, column, lat, lon in pending[:_MAX_PER_RUN]:
        code = photon.reverse_country(lat, lon)
        if code:
            with db_write() as conn:
                conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (code, row_id))
            written += 1
        time.sleep(_DELAY_SECONDS)

    # Only a sweep that left nothing behind counts as done; a partial run (hit
    # the cap, or the geocoder went away mid-way) retries on the next start.
    if written == len(pending):
        set_global_setting(_FLAG, "1")
    logger.info("Place country backfill: resolved %d/%d", written, len(pending))
    return written


def start_place_country_backfill() -> None:
    """Run the backfill on a daemon thread so startup is not blocked on it."""
    threading.Thread(target=_run_quietly, name="place-country-backfill", daemon=True).start()


def _run_quietly() -> None:
    try:
        backfill_place_countries()
    except Exception as e:  # noqa: BLE001 - a backfill must never break startup
        logger.warning("Place country backfill failed: %s", e)
