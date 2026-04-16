"""
Flight CRUD routes.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import can_access_flight, can_access_trip
from ..utils import calc_duration_minutes, calc_flight_status, now_iso, validate_flight_number

router = APIRouter(prefix="/api/flights", tags=["flights"])


@router.get("")
def list_flights(
    trip_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Return flights, optionally filtered by trip or status."""
    with db_conn() as conn:
        if trip_id:
            if not can_access_trip(trip_id, user["id"], conn):
                raise HTTPException(status_code=404, detail="Trip not found")
            query = "SELECT * FROM flights WHERE trip_id = ?"
            params: list = [trip_id]
            count_query = "SELECT COUNT(*) FROM flights WHERE trip_id = ?"
            count_params: list = [trip_id]
            if status:
                query += " AND status = ?"
                params.append(status)
                count_query += " AND status = ?"
                count_params.append(status)
        else:
            # User's own flights + flights from shared trips
            base_union = (
                "SELECT f.* FROM flights f WHERE f.user_id = ? "
                "UNION "
                "SELECT f.* FROM flights f "
                "JOIN trip_shares ts ON ts.trip_id = f.trip_id "
                "WHERE ts.user_id = ? AND ts.status = 'accepted'"
            )
            params = [user["id"], user["id"]]
            count_params = [user["id"], user["id"]]
            if status:
                query = f"SELECT * FROM ({base_union}) WHERE status = ?"
                params.append(status)
                count_query = f"SELECT COUNT(*) FROM ({base_union}) WHERE status = ?"
                count_params.append(status)
            else:
                query = base_union
                count_query = f"SELECT COUNT(*) FROM ({base_union})"

        query += " ORDER BY departure_datetime DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        total = conn.execute(count_query, count_params).fetchone()[0]

    return {
        "flights": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{flight_id}")
def get_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Return a single flight."""
    with db_conn() as conn:
        if not can_access_flight(flight_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Flight not found")
        row = conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flight not found")
    return dict(row)


@router.get("/{flight_id}/email")
def get_flight_email(flight_id: str, user: dict = Depends(get_current_user)):
    """Return the raw email body (HTML + text) stored for this flight."""
    with db_conn() as conn:
        if not can_access_flight(flight_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Flight not found")
        row = conn.execute(
            "SELECT email_body, email_subject, email_date FROM flights WHERE id = ?",
            (flight_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flight not found")
    return {
        "html_body": row["email_body"] or "",
        "email_subject": row["email_subject"] or "",
        "email_date": row["email_date"] or "",
    }


@router.get("/{flight_id}/aircraft")
async def get_flight_aircraft(flight_id: str, user: dict = Depends(get_current_user)):
    """Return cached aircraft info, or fetch from OpenSky if the flight is still active.

    Completed flights are not queried against OpenSky — the background aircraft
    sync job handles lookups while flights are airborne.
    """
    with db_conn() as conn:
        if not can_access_flight(flight_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Flight not found")
        row = conn.execute(
            "SELECT flight_number, arrival_datetime, aircraft_type, aircraft_icao, "
            "aircraft_registration, aircraft_fetched_at FROM flights WHERE id = ?",
            (flight_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flight not found")

    # Return cached result if we have one
    if row["aircraft_fetched_at"]:
        type_name = row["aircraft_type"] or ""
        icao24 = row["aircraft_icao"] or ""

        # Recovery: if type name or registration was wiped but ICAO24 is intact, resolve it now
        registration = row["aircraft_registration"] or ""
        if (not type_name or not registration) and icao24:
            from ..aircraft_api import _fetch_type_name_from_hexdb

            type_name, _, recovered_reg = await _fetch_type_name_from_hexdb(icao24)
            if recovered_reg and not registration:
                registration = recovered_reg
            if type_name:
                from ..database import db_write

                with db_write() as conn:
                    conn.execute(
                        "UPDATE flights SET aircraft_type = ?, aircraft_registration = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                        (type_name, registration, now_iso(), flight_id, user["id"]),
                    )

        return {
            "type_name": type_name,
            "icao24": icao24,
            "registration": row["aircraft_registration"] or "",
            "fetched_at": row["aircraft_fetched_at"],
        }

    # Don't hit OpenSky for completed flights — they're no longer airborne
    if row["arrival_datetime"]:
        try:
            arr = datetime.fromisoformat(row["arrival_datetime"])
            if calc_flight_status(arr) == "completed":
                return {}
        except ValueError:
            pass

    from ..aircraft_api import get_or_fetch_aircraft

    info = await get_or_fetch_aircraft(flight_id, row["flight_number"])
    return info


class FlightCreate(BaseModel):
    flight_number: str
    airline_name: str = ""
    airline_code: str = ""
    departure_airport: str
    departure_datetime: str
    arrival_airport: str
    arrival_datetime: str
    booking_reference: str = ""
    passenger_name: str = ""
    seat: str = ""
    cabin_class: str = ""
    departure_terminal: str = ""
    departure_gate: str = ""
    arrival_terminal: str = ""
    arrival_gate: str = ""
    notes: str = Field("", max_length=10000)
    trip_id: str | None = None


class FlightUpdate(BaseModel):
    flight_number: str | None = None
    airline_name: str | None = None
    airline_code: str | None = None
    departure_airport: str | None = None
    departure_datetime: str | None = None
    arrival_airport: str | None = None
    arrival_datetime: str | None = None
    booking_reference: str | None = None
    passenger_name: str | None = None
    seat: str | None = None
    cabin_class: str | None = None
    departure_terminal: str | None = None
    departure_gate: str | None = None
    arrival_terminal: str | None = None
    arrival_gate: str | None = None
    notes: str | None = Field(None, max_length=10000)
    trip_id: str | None = None
    status: str | None = None


@router.post("", status_code=201)
def create_flight(
    body: FlightCreate, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)
):
    """Manually create a flight."""
    if not validate_flight_number(body.flight_number):
        raise HTTPException(status_code=422, detail="Invalid flight number format")

    from ..timezone_utils import apply_airport_timezones

    now = now_iso()
    flight_id = str(uuid.uuid4())

    dep_obj = arr_obj = None
    try:
        dep_obj = datetime.fromisoformat(body.departure_datetime)
        arr_obj = datetime.fromisoformat(body.arrival_datetime)
    except (ValueError, TypeError):
        pass

    # Apply timezone lookup — converts local times to UTC (same as auto-synced flights)
    tz_info = apply_airport_timezones(
        {
            "departure_airport": body.departure_airport,
            "arrival_airport": body.arrival_airport,
            "departure_datetime": dep_obj,
            "arrival_datetime": arr_obj,
        }
    )
    departure_timezone = tz_info.get("departure_timezone")
    arrival_timezone = tz_info.get("arrival_timezone")

    # Use UTC-converted datetimes for storage so ORDER BY sorts correctly
    # alongside email-synced flights (which always store UTC).
    from ..utils import dt_to_iso

    dep_utc = tz_info.get("departure_datetime")
    arr_utc = tz_info.get("arrival_datetime")
    dep_iso = dt_to_iso(dep_utc) if dep_utc is not None else body.departure_datetime
    arr_iso = dt_to_iso(arr_utc) if arr_utc is not None else body.arrival_datetime

    duration_minutes = calc_duration_minutes(dep_utc or dep_obj, arr_utc or arr_obj)

    if body.trip_id:
        with db_conn() as conn:
            if not conn.execute(
                "SELECT id FROM trips WHERE id = ? AND user_id = ?",
                (body.trip_id, user["id"]),
            ).fetchone():
                raise HTTPException(403, "Trip not found or access denied")

    status = calc_flight_status(arr_utc or arr_obj)

    with db_write() as conn:
        conn.execute(
            """INSERT INTO flights (
                id, trip_id, airline_name, airline_code, flight_number,
                booking_reference, departure_airport, departure_datetime,
                departure_terminal, departure_gate, arrival_airport, arrival_datetime,
                arrival_terminal, arrival_gate, passenger_name, seat, cabin_class,
                duration_minutes, status, departure_timezone, arrival_timezone,
                is_manually_added, notes, user_id, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                1, ?, ?, ?, ?
            )""",
            (
                flight_id,
                body.trip_id,
                body.airline_name,
                body.airline_code,
                body.flight_number,
                body.booking_reference,
                body.departure_airport,
                dep_iso,
                body.departure_terminal,
                body.departure_gate,
                body.arrival_airport,
                arr_iso,
                body.arrival_terminal,
                body.arrival_gate,
                body.passenger_name,
                body.seat,
                body.cabin_class,
                duration_minutes,
                status,
                departure_timezone,
                arrival_timezone,
                body.notes,
                user["id"],
                now,
                now,
            ),
        )
        if body.trip_id:
            conn.execute(
                """UPDATE trips SET
                    start_date = (
                        SELECT DATE(departure_datetime)
                        FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) ASC LIMIT 1
                    ),
                    end_date = (
                        SELECT DATE(arrival_datetime)
                        FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) DESC LIMIT 1
                    ),
                    origin_airport = (
                        SELECT departure_airport FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) ASC LIMIT 1
                    ),
                    destination_airport = (
                        SELECT arrival_airport FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) DESC LIMIT 1
                    ),
                    updated_at = ?
                WHERE id = ?""",
                (body.trip_id, body.trip_id, body.trip_id, body.trip_id, now, body.trip_id),
            )

    from ..aircraft_sync import fetch_aircraft_for_new_flights

    background_tasks.add_task(fetch_aircraft_for_new_flights, [flight_id])

    return {"id": flight_id}


@router.patch("/{flight_id}")
def update_flight(flight_id: str, body: FlightUpdate, user: dict = Depends(get_current_user)):
    """Update flight fields."""
    from ..timezone_utils import apply_airport_timezones
    from ..utils import dt_to_iso

    with db_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM flights WHERE id = ? AND user_id = ?", (flight_id, user["id"])
        ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Flight not found")
    existing = dict(existing)

    if body.flight_number is not None and not validate_flight_number(body.flight_number):
        raise HTTPException(status_code=422, detail="Invalid flight number format")

    updates: dict = {}
    for field in (
        "flight_number",
        "airline_name",
        "airline_code",
        "booking_reference",
        "passenger_name",
        "seat",
        "cabin_class",
        "departure_terminal",
        "departure_gate",
        "arrival_terminal",
        "arrival_gate",
        "notes",
        "trip_id",
        "status",
    ):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val

    # When airports or datetimes change, re-run timezone conversion and recompute
    # duration/status so the stored datetimes stay in UTC format.
    times_changed = any(
        v is not None
        for v in (
            body.departure_airport,
            body.arrival_airport,
            body.departure_datetime,
            body.arrival_datetime,
        )
    )
    if times_changed:
        dep_airport = body.departure_airport or existing["departure_airport"]
        arr_airport = body.arrival_airport or existing["arrival_airport"]
        raw_dep = body.departure_datetime or existing["departure_datetime"]
        raw_arr = body.arrival_datetime or existing["arrival_datetime"]

        dep_obj = arr_obj = None
        try:
            dep_obj = datetime.fromisoformat(raw_dep)
        except (ValueError, TypeError):
            pass
        try:
            arr_obj = datetime.fromisoformat(raw_arr)
        except (ValueError, TypeError):
            pass

        tz_info = apply_airport_timezones(
            {
                "departure_airport": dep_airport,
                "arrival_airport": arr_airport,
                "departure_datetime": dep_obj,
                "arrival_datetime": arr_obj,
            }
        )
        dep_utc = tz_info.get("departure_datetime")
        arr_utc = tz_info.get("arrival_datetime")

        updates["departure_airport"] = dep_airport
        updates["arrival_airport"] = arr_airport
        updates["departure_datetime"] = dt_to_iso(dep_utc) if dep_utc is not None else raw_dep
        updates["arrival_datetime"] = dt_to_iso(arr_utc) if arr_utc is not None else raw_arr
        updates["departure_timezone"] = tz_info.get("departure_timezone")
        updates["arrival_timezone"] = tz_info.get("arrival_timezone")
        updates["duration_minutes"] = calc_duration_minutes(dep_utc or dep_obj, arr_utc or arr_obj)
        if body.status is None:
            updates["status"] = calc_flight_status(arr_utc or arr_obj)

    if not updates:
        return {"id": flight_id}

    now = now_iso()
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [flight_id, user["id"]]

    trip_id = updates.get("trip_id") or existing.get("trip_id")

    with db_write() as conn:
        conn.execute(f"UPDATE flights SET {set_clause} WHERE id = ? AND user_id = ?", values)
        if trip_id and times_changed:
            conn.execute(
                """UPDATE trips SET
                    start_date = (
                        SELECT DATE(departure_datetime) FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) ASC LIMIT 1
                    ),
                    end_date = (
                        SELECT DATE(arrival_datetime) FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) DESC LIMIT 1
                    ),
                    origin_airport = (
                        SELECT departure_airport FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) ASC LIMIT 1
                    ),
                    destination_airport = (
                        SELECT arrival_airport FROM flights WHERE trip_id = ?
                        ORDER BY datetime(departure_datetime) DESC LIMIT 1
                    ),
                    updated_at = ?
                WHERE id = ?""",
                (trip_id, trip_id, trip_id, trip_id, now, trip_id),
            )

    return {"id": flight_id}


@router.delete("/{flight_id}", status_code=204)
def delete_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Delete a flight (owner only)."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM flights WHERE id = ? AND user_id = ?", (flight_id, user["id"])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flight not found")
    with db_write() as conn:
        conn.execute("DELETE FROM flights WHERE id = ? AND user_id = ?", (flight_id, user["id"]))


@router.post("/{flight_id}/ungroup", status_code=201)
def ungroup_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Move a flight out of its current trip into a new solo trip."""
    import json

    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM flights WHERE id = ? AND user_id = ?", (flight_id, user["id"])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flight not found")

    flight = dict(row)
    if not flight.get("trip_id"):
        raise HTTPException(status_code=400, detail="Flight is not part of a trip")

    # Ensure the trip has more than one flight — no point ungrouping a solo flight
    with db_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM flights WHERE trip_id = ?", (flight["trip_id"],)
        ).fetchone()[0]
    if count <= 1:
        raise HTTPException(status_code=400, detail="Trip only has one flight; nothing to ungroup")

    dep = flight.get("departure_airport") or ""
    arr = flight.get("arrival_airport") or ""
    trip_name = f"{dep} → {arr}" if dep and arr else flight.get("flight_number") or "Flight"
    booking_ref = flight.get("booking_reference") or ""
    start_date = ""
    end_date = ""
    if flight.get("departure_datetime"):
        start_date = str(flight["departure_datetime"])[:10]
    if flight.get("arrival_datetime"):
        end_date = str(flight["arrival_datetime"])[:10]

    now = now_iso()
    new_trip_id = str(uuid.uuid4())

    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, start_date, end_date,
               origin_airport, destination_airport, is_auto_generated, user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                new_trip_id,
                trip_name,
                json.dumps([booking_ref] if booking_ref else []),
                start_date,
                end_date,
                dep,
                arr,
                user["id"],
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE flights SET trip_id = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (new_trip_id, now, flight_id, user["id"]),
        )

    return {"trip_id": new_trip_id}
