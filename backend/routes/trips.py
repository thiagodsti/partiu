"""
Trip CRUD routes.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import db_conn, db_write

router = APIRouter(prefix='/api/trips', tags=['trips'])


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_trip(row) -> dict:
    d = dict(row)
    # Parse booking_refs JSON
    try:
        d['booking_refs'] = json.loads(d.get('booking_refs') or '[]')
    except (json.JSONDecodeError, TypeError):
        d['booking_refs'] = []
    return d


@router.get('')
def list_trips():
    """Return all trips ordered by start_date descending."""
    with db_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM trips ORDER BY start_date DESC'
        ).fetchall()
        trips = [_row_to_trip(r) for r in rows]

        # Attach flight counts
        for trip in trips:
            count = conn.execute(
                'SELECT COUNT(*) FROM flights WHERE trip_id = ?', (trip['id'],)
            ).fetchone()[0]
            trip['flight_count'] = count

    return {'trips': trips}


@router.get('/{trip_id}')
def get_trip(trip_id: str):
    """Return a single trip with its flights."""
    with db_conn() as conn:
        row = conn.execute('SELECT * FROM trips WHERE id = ?', (trip_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Trip not found')
        trip = _row_to_trip(row)

        flights = conn.execute(
            'SELECT * FROM flights WHERE trip_id = ? ORDER BY departure_datetime',
            (trip_id,)
        ).fetchall()
        trip['flights'] = [dict(f) for f in flights]

    return trip


class TripCreate(BaseModel):
    name: str
    booking_refs: list[str] = []
    start_date: str = ''
    end_date: str = ''
    origin_airport: str = ''
    destination_airport: str = ''


class TripUpdate(BaseModel):
    name: str | None = None
    booking_refs: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    origin_airport: str | None = None
    destination_airport: str | None = None


@router.post('', status_code=201)
def create_trip(body: TripCreate):
    """Create a new trip manually."""
    now = _now_iso()
    trip_id = str(uuid.uuid4())

    with db_write() as conn:
        conn.execute(
            '''INSERT INTO trips (id, name, booking_refs, start_date, end_date,
               origin_airport, destination_airport, is_auto_generated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)''',
            (trip_id, body.name, json.dumps(body.booking_refs),
             body.start_date, body.end_date,
             body.origin_airport, body.destination_airport, now, now),
        )

    return {'id': trip_id, 'name': body.name}


@router.patch('/{trip_id}')
def update_trip(trip_id: str, body: TripUpdate):
    """Update trip fields."""
    with db_conn() as conn:
        row = conn.execute('SELECT * FROM trips WHERE id = ?', (trip_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Trip not found')

    updates = {}
    if body.name is not None:
        updates['name'] = body.name
    if body.booking_refs is not None:
        updates['booking_refs'] = json.dumps(body.booking_refs)
    if body.start_date is not None:
        updates['start_date'] = body.start_date
    if body.end_date is not None:
        updates['end_date'] = body.end_date
    if body.origin_airport is not None:
        updates['origin_airport'] = body.origin_airport
    if body.destination_airport is not None:
        updates['destination_airport'] = body.destination_airport

    if not updates:
        return {'id': trip_id}

    updates['updated_at'] = _now_iso()
    set_clause = ', '.join(f'{k} = ?' for k in updates)
    values = list(updates.values()) + [trip_id]

    with db_write() as conn:
        conn.execute(f'UPDATE trips SET {set_clause} WHERE id = ?', values)

    return {'id': trip_id}


@router.delete('/{trip_id}', status_code=204)
def delete_trip(trip_id: str):
    """Delete a trip (flights are unlinked, not deleted)."""
    now = _now_iso()
    with db_write() as conn:
        conn.execute(
            'UPDATE flights SET trip_id = NULL, updated_at = ? WHERE trip_id = ?',
            (now, trip_id)
        )
        conn.execute('DELETE FROM trips WHERE id = ?', (trip_id,))


@router.post('/{trip_id}/flights/{flight_id}')
def add_flight_to_trip(trip_id: str, flight_id: str):
    """Assign a flight to a trip."""
    now = _now_iso()
    with db_write() as conn:
        # Verify trip and flight exist
        if not conn.execute('SELECT id FROM trips WHERE id = ?', (trip_id,)).fetchone():
            raise HTTPException(status_code=404, detail='Trip not found')
        if not conn.execute('SELECT id FROM flights WHERE id = ?', (flight_id,)).fetchone():
            raise HTTPException(status_code=404, detail='Flight not found')

        conn.execute(
            'UPDATE flights SET trip_id = ?, updated_at = ? WHERE id = ?',
            (trip_id, now, flight_id)
        )
    return {'ok': True}


@router.delete('/{trip_id}/flights/{flight_id}')
def remove_flight_from_trip(trip_id: str, flight_id: str):
    """Unlink a flight from a trip."""
    now = _now_iso()
    with db_write() as conn:
        conn.execute(
            'UPDATE flights SET trip_id = NULL, updated_at = ? WHERE id = ? AND trip_id = ?',
            (now, flight_id, trip_id)
        )
    return {'ok': True}
