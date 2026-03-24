"""
Background job: refresh live flight status (delay/cancellation) for upcoming flights.

Strategy:
  - Runs every 60 minutes.
  - Only checks flights departing within the next 2 hours or currently active.
  - Only refreshes if live_status_fetched_at is NULL or older than 60 minutes.
  - Requires AVIATIONSTACK_API_KEY (OpenSky doesn't provide delay data).
  - Conserves API quota: skips completed/cancelled flights entirely.
"""

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx

from .database import db_conn, db_write

logger = logging.getLogger(__name__)

_STATUS_WINDOW_HOURS = 2  # check flights departing within this many hours
_REFRESH_INTERVAL = timedelta(hours=1)
_AVIATIONSTACK_BASE = "http://api.aviationstack.com/v1"
_TIMEOUT = 10.0


def run_flight_status_sync() -> dict:
    """Synchronous entry point for APScheduler (runs every 30 minutes)."""
    return asyncio.run(_run_flight_status_sync())


async def _fetch_status_from_aviationstack(flight_number: str, api_key: str) -> dict:
    """
    Fetch live status for a flight from AviationStack.
    Returns a dict with live_status, delays, and estimated times.
    """
    callsign = flight_number.replace(" ", "").upper()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_AVIATIONSTACK_BASE}/flights",
                params={"access_key": api_key, "flight_iata": callsign},
            )
            if resp.status_code != 200:
                logger.debug("AviationStack status check failed: HTTP %d", resp.status_code)
                return {}

            data = resp.json()
            flights = data.get("data") or []
            if not flights:
                logger.debug("AviationStack: no status data for %s", callsign)
                return {}

            f = flights[0]
            departure = f.get("departure") or {}
            arrival = f.get("arrival") or {}
            return {
                "flight_status": f.get("flight_status") or "",
                "departure_delay": departure.get("delay"),
                "arrival_delay": arrival.get("delay"),
                "departure_actual": departure.get("actual") or "",
                "arrival_estimated": arrival.get("estimated") or "",
            }

    except httpx.TimeoutException:
        logger.debug("AviationStack timeout for %s", callsign)
        return {}
    except Exception as e:
        logger.debug("AviationStack status error for %s: %s", callsign, e)
        return {}


async def _run_flight_status_sync() -> dict:
    from .config import settings

    if not settings.AVIATIONSTACK_API_KEY:
        logger.debug("Flight status sync skipped: AVIATIONSTACK_API_KEY not configured")
        return {"skipped": True}

    now = datetime.now(UTC)
    window_end = (now + timedelta(hours=_STATUS_WINDOW_HOURS)).isoformat()
    stale_cutoff = (now - _REFRESH_INTERVAL).isoformat()

    # Find upcoming/active flights within the window that need a status refresh,
    # along with user preferences and previous live status for change detection.
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT f.id, f.flight_number, f.departure_airport, f.arrival_airport,
                   f.trip_id, f.live_status AS prev_live_status,
                   f.live_departure_delay AS prev_dep_delay,
                   u.id AS user_id, u.notif_delay_alert
            FROM flights f
            JOIN users u ON f.user_id = u.id
            WHERE f.status IN ('upcoming', 'active')
              AND f.departure_datetime <= ?
              AND (f.arrival_datetime IS NULL OR f.arrival_datetime >= ?)
              AND (f.live_status_fetched_at IS NULL OR f.live_status_fetched_at <= ?)
            ORDER BY f.departure_datetime
            """,
            (window_end, now.isoformat(), stale_cutoff),
        ).fetchall()

    if not rows:
        logger.debug("Flight status sync: no flights need status refresh")
        return {"attempted": 0, "updated": 0}

    logger.info("Flight status sync: %d flight(s) to check", len(rows))
    now_iso = now.isoformat()
    attempted = updated = 0

    for row in rows:
        attempted += 1
        status_info = await _fetch_status_from_aviationstack(
            row["flight_number"], settings.AVIATIONSTACK_API_KEY
        )

        # Always update live_status_fetched_at so we don't re-check immediately on next run
        with db_write() as conn:
            conn.execute(
                """UPDATE flights
                   SET live_status = ?,
                       live_departure_delay = ?,
                       live_arrival_delay = ?,
                       live_departure_actual = ?,
                       live_arrival_estimated = ?,
                       live_status_fetched_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    status_info.get("flight_status") or None,
                    status_info.get("departure_delay"),
                    status_info.get("arrival_delay"),
                    status_info.get("departure_actual") or None,
                    status_info.get("arrival_estimated") or None,
                    now_iso,
                    now_iso,
                    row["id"],
                ),
            )

        if status_info:
            updated += 1
            delay = status_info.get("departure_delay")
            flight_status = status_info.get("flight_status") or "unknown"
            logger.info(
                "Flight status sync: %s → %s%s",
                row["flight_number"],
                flight_status,
                f" (+{delay}min delay)" if delay else "",
            )

            if row["notif_delay_alert"]:
                _maybe_send_alert(row, status_info)

    logger.info("Flight status sync: attempted=%d updated=%d", attempted, updated)
    return {"attempted": attempted, "updated": updated}


_DELAY_ALERT_THRESHOLD = 15  # minutes — below this is noise


def _maybe_send_alert(row: sqlite3.Row, status_info: dict) -> None:
    """Send a push notification if something significant changed for this flight."""
    from .push import already_sent, log_sent, send_push

    flight_id = str(row["id"])
    user_id = row["user_id"]
    flight_number = row["flight_number"]
    dep = row["departure_airport"]
    arr = row["arrival_airport"]
    url = f"/#/trips/{row['trip_id']}" if row["trip_id"] else "/#/"

    new_status = status_info.get("flight_status") or ""
    new_delay = status_info.get("departure_delay") or 0
    prev_status = row["prev_live_status"] or ""
    prev_delay = row["prev_dep_delay"] or 0

    # Cancellation — send once
    if new_status == "cancelled" and prev_status != "cancelled":
        if not already_sent(user_id, flight_id, "delay_alert_cancelled"):
            payload = {
                "title": f"Flight {flight_number} cancelled",
                "body": f"{dep} → {arr}",
                "url": url,
            }
            if send_push(user_id, payload):
                log_sent(user_id, flight_id, "delay_alert_cancelled")
                logger.info(
                    "Sent delay_alert_cancelled to user %d for flight %s", user_id, flight_id
                )
        return

    # Diversion — send once
    if new_status == "diverted" and prev_status != "diverted":
        if not already_sent(user_id, flight_id, "delay_alert_diverted"):
            payload = {
                "title": f"Flight {flight_number} diverted",
                "body": f"{dep} → {arr}",
                "url": url,
            }
            if send_push(user_id, payload):
                log_sent(user_id, flight_id, "delay_alert_diverted")
                logger.info(
                    "Sent delay_alert_diverted to user %d for flight %s", user_id, flight_id
                )
        return

    # Delay — send once when departure delay first crosses the threshold
    if new_delay >= _DELAY_ALERT_THRESHOLD and prev_delay < _DELAY_ALERT_THRESHOLD:
        if not already_sent(user_id, flight_id, "delay_alert_delay"):
            payload = {
                "title": f"Flight {flight_number} delayed +{new_delay} min",
                "body": f"{dep} → {arr}",
                "url": url,
            }
            if send_push(user_id, payload):
                log_sent(user_id, flight_id, "delay_alert_delay")
                logger.info("Sent delay_alert_delay to user %d for flight %s", user_id, flight_id)
