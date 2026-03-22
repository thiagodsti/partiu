"""
Flight persistence helpers — insert, update, and look up flight rows in SQLite.
"""

import uuid

from .database import db_conn, db_write
from .utils import calc_duration_minutes, calc_flight_status, dt_to_iso, now_iso


def find_existing_flight(flight_number: str, departure_date: str, user_id: int) -> dict | None:
    """Find an existing non-manual flight by flight_number and departure date."""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT * FROM flights
               WHERE flight_number = ?
               AND substr(departure_datetime, 1, 10) = ?
               AND is_manually_added = 0
               AND user_id = ?
               LIMIT 1""",
            (flight_number, departure_date, user_id),
        ).fetchone()
        return dict(row) if row else None


def insert_flight(flight_data: dict, email_msg, user_id: int) -> str | None:
    """
    Insert a new flight row using INSERT OR IGNORE (dedup by email_message_id).
    Returns the new flight id if inserted, or None if it was a duplicate.
    """
    now = now_iso()
    flight_id = str(uuid.uuid4())

    dep_dt = flight_data.get("departure_datetime")
    arr_dt = flight_data.get("arrival_datetime")
    dep_iso = dt_to_iso(dep_dt)
    arr_iso = dt_to_iso(arr_dt)
    duration_minutes = calc_duration_minutes(dep_dt, arr_dt)
    status = calc_flight_status(arr_dt)

    msg_id_for_dedup = f"{email_msg.message_id}:{flight_data['flight_number']}"

    with db_write() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO flights (
                id, trip_id, airline_name, airline_code, flight_number,
                booking_reference, departure_airport, departure_datetime,
                departure_terminal, departure_gate, arrival_airport, arrival_datetime,
                arrival_terminal, arrival_gate, passenger_name, seat, cabin_class,
                duration_minutes, status, departure_timezone, arrival_timezone,
                email_message_id, email_subject, email_date, email_body,
                is_manually_added, notes, user_id, created_at, updated_at
            ) VALUES (
                ?, NULL, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                0, NULL, ?, ?, ?
            )""",
            (
                flight_id,
                flight_data.get("airline_name", ""),
                flight_data.get("airline_code", ""),
                flight_data["flight_number"],
                flight_data.get("booking_reference", ""),
                flight_data["departure_airport"],
                dep_iso,
                flight_data.get("departure_terminal", ""),
                flight_data.get("departure_gate", ""),
                flight_data["arrival_airport"],
                arr_iso,
                flight_data.get("arrival_terminal", ""),
                flight_data.get("arrival_gate", ""),
                flight_data.get("passenger_name", ""),
                flight_data.get("seat", ""),
                flight_data.get("cabin_class", ""),
                duration_minutes,
                status,
                flight_data.get("departure_timezone"),
                flight_data.get("arrival_timezone"),
                msg_id_for_dedup,
                (email_msg.subject or "")[:512],
                dt_to_iso(email_msg.date),
                email_msg.html_body,
                user_id,
                now,
                now,
            ),
        )
    return flight_id if cursor.rowcount else None


def update_flight(existing_id: str, flight_data: dict, email_msg):
    """Update an existing flight with newer email data."""
    now = now_iso()
    dep_dt = flight_data.get("departure_datetime")
    arr_dt = flight_data.get("arrival_datetime")
    dep_iso = dt_to_iso(dep_dt)
    arr_iso = dt_to_iso(arr_dt)
    duration_minutes = calc_duration_minutes(dep_dt, arr_dt)
    status = calc_flight_status(arr_dt)
    msg_id_for_dedup = f"{email_msg.message_id}:{flight_data['flight_number']}"

    with db_write() as conn:
        conn.execute(
            """UPDATE flights SET
                departure_datetime = ?, arrival_datetime = ?,
                departure_terminal = ?, arrival_terminal = ?,
                departure_gate = ?, arrival_gate = ?,
                seat = ?, cabin_class = ?,
                booking_reference = ?, passenger_name = ?,
                duration_minutes = ?, status = ?,
                departure_timezone = ?, arrival_timezone = ?,
                email_message_id = ?, email_subject = ?, email_date = ?, email_body = ?,
                updated_at = ?
               WHERE id = ?""",
            (
                dep_iso,
                arr_iso,
                flight_data.get("departure_terminal", ""),
                flight_data.get("arrival_terminal", ""),
                flight_data.get("departure_gate", ""),
                flight_data.get("arrival_gate", ""),
                flight_data.get("seat", ""),
                flight_data.get("cabin_class", ""),
                flight_data.get("booking_reference", ""),
                flight_data.get("passenger_name", ""),
                duration_minutes,
                status,
                flight_data.get("departure_timezone"),
                flight_data.get("arrival_timezone"),
                msg_id_for_dedup,
                (email_msg.subject or "")[:512],
                dt_to_iso(email_msg.date),
                email_msg.html_body,
                now,
                existing_id,
            ),
        )


def update_flight_from_bcbp(existing_id: str, bcbp_leg: dict):
    """Patch an existing flight with data from a boarding pass (seat, cabin, pax name, pnr)."""
    updates = {}
    if bcbp_leg.get("seat"):
        updates["seat"] = bcbp_leg["seat"]
    if bcbp_leg.get("cabin_class"):
        updates["cabin_class"] = bcbp_leg["cabin_class"]
    if bcbp_leg.get("passenger_name"):
        updates["passenger_name"] = bcbp_leg["passenger_name"]
    if bcbp_leg.get("booking_reference"):
        updates["booking_reference"] = bcbp_leg["booking_reference"]
    if not updates:
        return
    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [existing_id]
    with db_write() as conn:
        conn.execute(f"UPDATE flights SET {set_clause} WHERE id = ?", values)
