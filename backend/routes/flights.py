"""
Flight CRUD routes.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel

from ..database import db_conn, db_write
from ..auth import get_current_user

router = APIRouter(prefix='/api/flights', tags=['flights'])


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@router.get('')
def list_flights(
    trip_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Return flights, optionally filtered by trip or status."""
    query = 'SELECT * FROM flights WHERE user_id = ?'
    params: list = [user['id']]

    if trip_id:
        query += ' AND trip_id = ?'
        params.append(trip_id)
    if status:
        query += ' AND status = ?'
        params.append(status)

    query += ' ORDER BY departure_datetime DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])

    # Build count query params (same as main query without limit/offset)
    count_params: list = [user['id']]
    count_query = 'SELECT COUNT(*) FROM flights WHERE user_id = ?'
    if trip_id:
        count_query += ' AND trip_id = ?'
        count_params.append(trip_id)
    if status:
        count_query += ' AND status = ?'
        count_params.append(status)

    with db_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        total = conn.execute(count_query, count_params).fetchone()[0]

    return {
        'flights': [dict(r) for r in rows],
        'total': total,
        'limit': limit,
        'offset': offset,
    }


@router.get('/{flight_id}')
def get_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Return a single flight."""
    with db_conn() as conn:
        row = conn.execute(
            'SELECT * FROM flights WHERE id = ? AND user_id = ?', (flight_id, user['id'])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Flight not found')
    return dict(row)


@router.get('/{flight_id}/email')
def get_flight_email(flight_id: str, user: dict = Depends(get_current_user)):
    """Return the raw email body (HTML + text) stored for this flight."""
    with db_conn() as conn:
        row = conn.execute(
            'SELECT email_body, email_subject, email_date FROM flights WHERE id = ? AND user_id = ?',
            (flight_id, user['id'])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Flight not found')
    return {
        'html_body': row['email_body'] or '',
        'email_subject': row['email_subject'] or '',
        'email_date': row['email_date'] or '',
    }


@router.get('/{flight_id}/aircraft')
async def get_flight_aircraft(flight_id: str, user: dict = Depends(get_current_user)):
    """Return cached aircraft info, or fetch from OpenSky if the flight is still active.

    Completed flights are not queried against OpenSky — the background aircraft
    sync job handles lookups while flights are airborne.
    """
    with db_conn() as conn:
        row = conn.execute(
            'SELECT flight_number, arrival_datetime, aircraft_type, aircraft_icao, '
            'aircraft_registration, aircraft_fetched_at FROM flights WHERE id = ? AND user_id = ?',
            (flight_id, user['id']),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='Flight not found')

    # Return cached result if we have one
    if row['aircraft_fetched_at']:
        type_name = row['aircraft_type'] or ''
        icao24 = row['aircraft_icao'] or ''

        # Recovery: if type name or registration was wiped but ICAO24 is intact, resolve it now
        registration = row['aircraft_registration'] or ''
        if (not type_name or not registration) and icao24:
            from ..aircraft_api import _fetch_type_name_from_hexdb
            type_name, _, recovered_reg = await _fetch_type_name_from_hexdb(icao24)
            if recovered_reg and not registration:
                registration = recovered_reg
            if type_name:
                from ..database import db_write
                from datetime import datetime, timezone
                with db_write() as conn:
                    conn.execute(
                        'UPDATE flights SET aircraft_type = ?, aircraft_registration = ?, updated_at = ? WHERE id = ? AND user_id = ?',
                        (type_name, registration, datetime.now(timezone.utc).isoformat(), flight_id, user['id']),
                    )

        return {
            'type_name':    type_name,
            'icao24':       icao24,
            'registration': row['aircraft_registration'] or '',
            'fetched_at':   row['aircraft_fetched_at'],
        }

    # Don't hit OpenSky for completed flights — they're no longer airborne
    if row['arrival_datetime']:
        try:
            arr = datetime.fromisoformat(row['arrival_datetime'])
            if arr.tzinfo is None:
                arr = arr.replace(tzinfo=timezone.utc)
            if arr < datetime.now(timezone.utc):
                return {}
        except ValueError:
            pass

    from ..aircraft_api import get_or_fetch_aircraft
    info = await get_or_fetch_aircraft(flight_id, row['flight_number'])
    return info


class FlightCreate(BaseModel):
    flight_number: str
    airline_name: str = ''
    airline_code: str = ''
    departure_airport: str
    departure_datetime: str
    arrival_airport: str
    arrival_datetime: str
    booking_reference: str = ''
    passenger_name: str = ''
    seat: str = ''
    cabin_class: str = ''
    departure_terminal: str = ''
    departure_gate: str = ''
    arrival_terminal: str = ''
    arrival_gate: str = ''
    notes: str = ''
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
    notes: str | None = None
    trip_id: str | None = None
    status: str | None = None


@router.post('', status_code=201)
def create_flight(body: FlightCreate, background_tasks: BackgroundTasks,
                  user: dict = Depends(get_current_user)):
    """Manually create a flight."""
    now = _now_iso()
    flight_id = str(uuid.uuid4())

    # Calculate duration
    duration_minutes = None
    try:
        dep = datetime.fromisoformat(body.departure_datetime)
        arr = datetime.fromisoformat(body.arrival_datetime)
        delta = arr - dep
        minutes = int(delta.total_seconds() / 60)
        if minutes > 0:
            duration_minutes = minutes
    except (ValueError, TypeError):
        pass

    with db_write() as conn:
        conn.execute(
            '''INSERT INTO flights (
                id, trip_id, airline_name, airline_code, flight_number,
                booking_reference, departure_airport, departure_datetime,
                departure_terminal, departure_gate, arrival_airport, arrival_datetime,
                arrival_terminal, arrival_gate, passenger_name, seat, cabin_class,
                duration_minutes, status, is_manually_added, notes, user_id, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, 'upcoming', 1, ?, ?, ?, ?
            )''',
            (
                flight_id, body.trip_id,
                body.airline_name, body.airline_code, body.flight_number,
                body.booking_reference, body.departure_airport, body.departure_datetime,
                body.departure_terminal, body.departure_gate,
                body.arrival_airport, body.arrival_datetime,
                body.arrival_terminal, body.arrival_gate,
                body.passenger_name, body.seat, body.cabin_class,
                duration_minutes,
                body.notes, user['id'], now, now,
            ),
        )

    from ..aircraft_sync import fetch_aircraft_for_new_flights
    background_tasks.add_task(fetch_aircraft_for_new_flights, [flight_id])

    return {'id': flight_id}


@router.patch('/{flight_id}')
def update_flight(flight_id: str, body: FlightUpdate, user: dict = Depends(get_current_user)):
    """Update flight fields."""
    with db_conn() as conn:
        if not conn.execute(
            'SELECT id FROM flights WHERE id = ? AND user_id = ?', (flight_id, user['id'])
        ).fetchone():
            raise HTTPException(status_code=404, detail='Flight not found')

    updates = {}
    for field in (
        'flight_number', 'airline_name', 'airline_code',
        'departure_airport', 'departure_datetime', 'arrival_airport', 'arrival_datetime',
        'booking_reference', 'passenger_name', 'seat', 'cabin_class',
        'departure_terminal', 'departure_gate', 'arrival_terminal', 'arrival_gate',
        'notes', 'trip_id', 'status',
    ):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val

    if not updates:
        return {'id': flight_id}

    updates['updated_at'] = _now_iso()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [flight_id, user['id']]

    with db_write() as conn:
        conn.execute(f'UPDATE flights SET {set_clause} WHERE id = ? AND user_id = ?', values)

    return {'id': flight_id}


@router.delete('/{flight_id}', status_code=204)
def delete_flight(flight_id: str, user: dict = Depends(get_current_user)):
    """Delete a flight."""
    with db_write() as conn:
        conn.execute('DELETE FROM flights WHERE id = ? AND user_id = ?', (flight_id, user['id']))
