"""
Background job: fetch aircraft type for today's flights via AviationStack.

Strategy:
  - Daily job: sweep flights that departed within the last 24h and have no aircraft data.
  - Immediate trigger: when a new flight is added, try right away for that specific flight.
  - If a source returns no data, leave aircraft_fetched_at NULL so the daily job retries.
  - Give up 24h after arrival (mark as tried with empty values).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from .database import db_conn, db_write
from .utils import now_iso

logger = logging.getLogger(__name__)

_GIVE_UP_AFTER = timedelta(hours=24)
_BACKOFF_SCHEDULE = [timedelta(hours=1), timedelta(hours=6), timedelta(hours=24)]


# ---------------------------------------------------------------------------
# Daily sweep (called by scheduler)
# ---------------------------------------------------------------------------


def run_aircraft_sync() -> dict:
    """Synchronous entry point for APScheduler (runs daily)."""
    return asyncio.run(_run_aircraft_sync())


async def _recover_missing_aircraft_names() -> int:
    """
    For flights that have an ICAO24 stored but lost their aircraft_type or registration
    (e.g. from the bad migration), recover the name from hexdb.io using the stored ICAO24.
    """
    from .aircraft_api import _fetch_type_name_from_hexdb

    with db_conn() as conn:
        rows = conn.execute(
            """SELECT id, aircraft_icao FROM flights
               WHERE aircraft_icao != '' AND aircraft_icao IS NOT NULL
                 AND (aircraft_type IS NULL OR aircraft_type = ''
                      OR aircraft_registration IS NULL OR aircraft_registration = '')"""
        ).fetchall()

    if not rows:
        return 0

    logger.info("Aircraft recovery: %d flight(s) with ICAO24 but missing name/reg", len(rows))
    recovered = 0
    ts = now_iso()

    for row in rows:
        type_name, _, registration = await _fetch_type_name_from_hexdb(row["aircraft_icao"])
        if type_name or registration:
            with db_write() as conn:
                conn.execute(
                    "UPDATE flights SET aircraft_type = ?, aircraft_registration = ?, updated_at = ? WHERE id = ?",
                    (type_name, registration, ts, row["id"]),
                )
            recovered += 1
            logger.info(
                "Aircraft recovery: %s → %s / %s", row["aircraft_icao"], type_name, registration
            )

    return recovered


async def _run_aircraft_sync() -> dict:

    # First recover any flights that have ICAO24 but lost their name/registration
    recovered = await _recover_missing_aircraft_names()
    if recovered:
        logger.info("Aircraft sync: recovered %d flight(s) from stored ICAO24", recovered)

    now = datetime.now(UTC)
    window_start = (now - timedelta(hours=24)).isoformat()
    in_24h = (now + timedelta(hours=24)).isoformat()

    with db_conn() as conn:
        # Flights with no aircraft data yet
        rows = conn.execute(
            """
            SELECT id, flight_number, arrival_datetime, departure_datetime
            FROM flights
            WHERE aircraft_fetched_at IS NULL
              AND status != 'cancelled'
              AND departure_datetime >= ?
              AND departure_datetime <= ?
              AND (aircraft_next_retry_at IS NULL OR aircraft_next_retry_at <= ?)
            ORDER BY departure_datetime
            """,
            (window_start, now.isoformat(), now.isoformat()),
        ).fetchall()

        # Flights fetched early (unconfirmed) that are now within 24h of departure —
        # re-fetch because the API is more accurate close to the live window.
        refresh_rows = conn.execute(
            """
            SELECT id, flight_number, arrival_datetime, departure_datetime
            FROM flights
            WHERE aircraft_fetched_at IS NOT NULL
              AND aircraft_confirmed = 0
              AND status != 'cancelled'
              AND departure_datetime >= ?
              AND departure_datetime <= ?
            ORDER BY departure_datetime
            """,
            (window_start, in_24h),
        ).fetchall()

    # Combine, deduplicating by id (null-fetched rows take precedence)
    seen = {r["id"] for r in rows}
    all_rows = list(rows) + [r for r in refresh_rows if r["id"] not in seen]

    if not all_rows:
        logger.debug("Aircraft sync: no eligible flights in window")
        return {"attempted": 0, "updated": 0, "given_up": 0}

    logger.info("Aircraft sync: %d flight(s) to check", len(all_rows))
    return await _fetch_rows(all_rows)


# ---------------------------------------------------------------------------
# Immediate trigger (called when new flights are added)
# ---------------------------------------------------------------------------


def fetch_aircraft_for_new_flights(flight_ids: list[str]) -> None:
    """Try to fetch aircraft info immediately for a list of newly added flight IDs."""
    if not flight_ids:
        return
    asyncio.run(_fetch_for_flight_ids(flight_ids))


async def _fetch_for_flight_ids(flight_ids: list[str]) -> None:
    placeholders = ",".join("?" * len(flight_ids))
    ts = now_iso()
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, flight_number, arrival_datetime, departure_datetime
            FROM flights
            WHERE id IN ({placeholders})
              AND aircraft_fetched_at IS NULL
              AND status != 'cancelled'
              AND (aircraft_next_retry_at IS NULL OR aircraft_next_retry_at <= ?)
            """,
            [*flight_ids, ts],
        ).fetchall()

    if rows:
        await _fetch_rows(rows)


# ---------------------------------------------------------------------------
# Shared fetch logic
# ---------------------------------------------------------------------------


async def _fetch_rows(rows) -> dict:
    from .aircraft_api import fetch_aircraft_info

    now = datetime.now(UTC)
    ts = now.isoformat()
    attempted = updated = given_up = 0

    for row in rows:
        # Give up if arrival was more than 24h ago
        arr_str = row["arrival_datetime"]
        if arr_str:
            try:
                arr = datetime.fromisoformat(arr_str)
                if arr.tzinfo is None:
                    arr = arr.replace(tzinfo=UTC)
                if now - arr > _GIVE_UP_AFTER:
                    with db_write() as conn:
                        conn.execute(
                            "UPDATE flights SET aircraft_fetched_at = ?, updated_at = ? WHERE id = ?",
                            (ts, ts, row["id"]),
                        )
                    given_up += 1
                    logger.debug(
                        "Aircraft sync: giving up on %s (>24h past arrival)", row["flight_number"]
                    )
                    continue
            except ValueError:
                pass

        attempted += 1
        info = await fetch_aircraft_info(row["flight_number"])

        if info.get("icao24") or info.get("type_name"):
            # Mark confirmed only when fetching within the live window (≤24h before departure)
            confirmed = 0
            dep_str = row["departure_datetime"]
            if dep_str:
                try:
                    dep = datetime.fromisoformat(dep_str)
                    if dep.tzinfo is None:
                        dep = dep.replace(tzinfo=UTC)
                    if now >= dep - timedelta(hours=24):
                        confirmed = 1
                except ValueError:
                    pass

            with db_write() as conn:
                conn.execute(
                    """UPDATE flights
                       SET aircraft_type = ?, aircraft_icao = ?, aircraft_registration = ?,
                           aircraft_fetched_at = ?,
                           aircraft_confirmed = ?,
                           aircraft_fetch_attempts = 0, aircraft_next_retry_at = NULL,
                           live_status = ?, live_departure_delay = ?, live_arrival_delay = ?,
                           live_departure_actual = ?, live_arrival_estimated = ?,
                           live_status_fetched_at = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (
                        info.get("type_name") or "",
                        info.get("icao24") or "",
                        info.get("registration") or "",
                        ts,
                        confirmed,
                        info.get("flight_status") or None,
                        info.get("departure_delay"),
                        info.get("arrival_delay"),
                        info.get("departure_actual") or None,
                        info.get("arrival_estimated") or None,
                        ts,
                        ts,
                        row["id"],
                    ),
                )
            updated += 1
            logger.info(
                "Aircraft sync: %s → %s (%s)",
                row["flight_number"],
                info.get("type_name") or "?",
                info.get("icao24") or "?",
            )
        else:
            # Schedule next retry with exponential backoff (1h → 6h → 24h)
            with db_conn() as conn:
                attempts = conn.execute(
                    "SELECT aircraft_fetch_attempts FROM flights WHERE id = ?", (row["id"],)
                ).fetchone()
            current_attempts = (attempts["aircraft_fetch_attempts"] if attempts else 0) or 0
            backoff = _BACKOFF_SCHEDULE[min(current_attempts, len(_BACKOFF_SCHEDULE) - 1)]
            next_retry = (now + backoff).isoformat()
            with db_write() as conn:
                conn.execute(
                    """UPDATE flights
                       SET aircraft_fetch_attempts = aircraft_fetch_attempts + 1,
                           aircraft_next_retry_at = ?,
                           updated_at = ?
                       WHERE id = ?""",
                    (next_retry, ts, row["id"]),
                )
            logger.debug(
                "Aircraft sync: no data for %s — retry after %s (attempt %d)",
                row["flight_number"],
                next_retry,
                current_attempts + 1,
            )

    logger.info("Aircraft sync: attempted=%d updated=%d given_up=%d", attempted, updated, given_up)
    return {"attempted": attempted, "updated": updated, "given_up": given_up}
