"""
Scheduler job that checks for upcoming flights and sends push notifications.

Runs every 30 minutes.

Notification types:
  - flight_reminder   : 2 h before departure (window: [1h50m, 2h20m])
  - checkin_reminder  : 24 h before departure (window: [23h, 25h])
  - trip_reminder     : 1 day before trip start (window: [23h, 25h])
"""

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

_FLIGHT_WINDOW = (timedelta(hours=1, minutes=50), timedelta(hours=2, minutes=20))
_CHECKIN_WINDOW = (timedelta(hours=23), timedelta(hours=25))
_TRIP_WINDOW = (timedelta(hours=23), timedelta(hours=25))


def run_push_notifications() -> None:
    """Check for upcoming flights and send push notifications to all users."""
    try:
        from .database import db_conn

        with db_conn() as conn:
            users = conn.execute(
                "SELECT id, notif_flight_reminder, notif_checkin_reminder, notif_trip_reminder FROM users"
            ).fetchall()

        for user in users:
            user_id = user["id"]
            try:
                _check_user(
                    user_id=user_id,
                    notif_flight=bool(user["notif_flight_reminder"]),
                    notif_checkin=bool(user["notif_checkin_reminder"]),
                    notif_trip=bool(user["notif_trip_reminder"]),
                )
            except Exception:
                logger.exception("Error processing notifications for user %d", user_id)
    except Exception:
        logger.exception("Error in run_push_notifications")


def _check_user(
    user_id: int,
    notif_flight: bool,
    notif_checkin: bool,
    notif_trip: bool,
) -> None:
    from .database import db_conn
    from .push import already_sent, log_sent, send_push

    now = datetime.now(UTC)

    # ---- Per-flight notifications ----
    if notif_flight or notif_checkin:
        with db_conn() as conn:
            flights = conn.execute(
                """SELECT id, flight_number, departure_airport, arrival_airport,
                          departure_datetime, airline_name, trip_id
                   FROM flights
                   WHERE user_id = ? AND status = 'upcoming'
                     AND departure_datetime IS NOT NULL
                   ORDER BY departure_datetime""",
                (user_id,),
            ).fetchall()

        for row in flights:
            dep_dt_str = row["departure_datetime"]
            try:
                dep_dt = datetime.fromisoformat(dep_dt_str)
                if dep_dt.tzinfo is None:
                    dep_dt = dep_dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            time_until = dep_dt - now

            if notif_flight and _FLIGHT_WINDOW[0] <= time_until <= _FLIGHT_WINDOW[1]:
                fid = str(row["id"])
                if not already_sent(user_id, fid, "flight_reminder"):
                    mins = int(time_until.total_seconds() / 60)
                    payload = {
                        "title": f"Flight {row['flight_number']} in ~{mins} min",
                        "body": f"{row['departure_airport']} → {row['arrival_airport']}",
                        "url": f"/#/trips/{row['trip_id']}" if row["trip_id"] else "/#/",
                    }
                    if send_push(user_id, payload):
                        log_sent(user_id, fid, "flight_reminder")
                        logger.info("Sent flight_reminder to user %d for flight %s", user_id, fid)

            if notif_checkin and _CHECKIN_WINDOW[0] <= time_until <= _CHECKIN_WINDOW[1]:
                fid = str(row["id"])
                if not already_sent(user_id, fid, "checkin_reminder"):
                    payload = {
                        "title": f"Check-in open: {row['flight_number']}",
                        "body": f"{row['departure_airport']} → {row['arrival_airport']} — departs tomorrow",
                        "url": f"/#/trips/{row['trip_id']}" if row["trip_id"] else "/#/",
                    }
                    if send_push(user_id, payload):
                        log_sent(user_id, fid, "checkin_reminder")
                        logger.info("Sent checkin_reminder to user %d for flight %s", user_id, fid)

    # ---- Trip reminder (1 day before trip start) ----
    if notif_trip:
        with db_conn() as conn:
            trips = conn.execute(
                """SELECT id, name, start_date FROM trips
                   WHERE user_id = ? AND start_date IS NOT NULL""",
                (user_id,),
            ).fetchall()

        for row in trips:
            try:
                start_dt = datetime.fromisoformat(row["start_date"]).replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            # Treat start_date as midnight UTC — time_until is to start of trip day
            time_until = start_dt - now

            if _TRIP_WINDOW[0] <= time_until <= _TRIP_WINDOW[1]:
                tid = str(row["id"])
                if not already_sent(user_id, tid, "trip_reminder"):
                    payload = {
                        "title": f"Trip tomorrow: {row['name']}",
                        "body": "Your trip starts tomorrow. Have a great journey!",
                        "url": f"/#/trips/{tid}",
                    }
                    if send_push(user_id, payload):
                        log_sent(user_id, tid, "trip_reminder")
                        logger.info("Sent trip_reminder to user %d for trip %s", user_id, tid)
