"""
Auto-grouping logic for flights into trips.
Groups flights by booking reference and time proximity (like TripIt).

Adapted from AdventureLog grouping.py — uses raw SQLite instead of Django ORM.
"""

import json
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .database import db_conn, db_write
from .utils import now_iso

logger = logging.getLogger(__name__)

_MAX_GAP = timedelta(hours=48)
_CONNECTION_THRESHOLD = timedelta(hours=24)


def _dt_from_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _fetch_ungrouped_flights(user_id: int | None) -> list[dict]:
    """Return all flights not yet assigned to a trip, ordered by departure time."""
    with db_conn() as conn:
        if user_id is not None:
            rows = conn.execute(
                "SELECT * FROM flights WHERE trip_id IS NULL AND user_id = ? ORDER BY departure_datetime",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM flights WHERE trip_id IS NULL ORDER BY departure_datetime"
            ).fetchall()
    return [dict(r) for r in rows]


def auto_group_flights(user_id: int | None = None) -> dict:
    """
    Auto-group ungrouped flights into trips.

    Strategy:
    1. Group by booking_reference if available (same booking = same trip)
    2. For remaining flights, group by time proximity (flights within 48h)
    3. Merge overlapping groups (multiple bookings in same trip)

    Returns a summary dict.
    """
    ungrouped = _fetch_ungrouped_flights(user_id)

    groups_created = 0
    flights_grouped = 0

    if not ungrouped:
        merged = _merge_overlapping_groups(max_gap=_MAX_GAP, user_id=user_id)
        return {
            'groups_created': 0,
            'flights_grouped': 0,
            'groups_merged': merged,
            'message': 'No ungrouped flights found' + (f', merged {merged} groups' if merged else ''),
        }

    # Phase 1: Group by booking reference
    by_booking: dict[str, list[dict]] = defaultdict(list)
    no_booking: list[dict] = []

    for flight in ungrouped:
        ref = (flight.get('booking_reference') or '').strip()
        if ref:
            by_booking[ref].append(flight)
        else:
            no_booking.append(flight)

    for booking_ref, flights in by_booking.items():
        trip_id = _create_trip_for_flights(flights, booking_ref, user_id=user_id)
        if trip_id:
            groups_created += 1
            flights_grouped += len(flights)

    # Phase 2: Group remaining ungrouped flights by time proximity
    remaining = _fetch_ungrouped_flights(user_id)

    if remaining:
        proximity_groups = _group_by_proximity(remaining, max_gap=_MAX_GAP)
        for cluster in proximity_groups:
            if len(cluster) >= 2:
                trip_id = _create_trip_for_flights(cluster, user_id=user_id)
                if trip_id:
                    groups_created += 1
                    flights_grouped += len(cluster)

    # Phase 3: Merge overlapping groups
    merged = _merge_overlapping_groups(max_gap=_MAX_GAP, user_id=user_id)
    if merged:
        logger.info("Merged %d overlapping groups", merged)

    return {
        'groups_created': groups_created,
        'flights_grouped': flights_grouped,
        'groups_merged': merged,
        'message': f'Created {groups_created} trips with {flights_grouped} flights',
    }


def _find_trip_destination(flights: list[dict], origin: str) -> str:
    """
    Determine the main destination of a trip.

    For a one-way trip (ARN → FRA → GRU), returns the last arrival (GRU).
    For a round-trip (ARN → GRU → ARN), returns the first real destination
    where the traveller stays 24h+ before heading back.
    """
    if not flights:
        return origin

    last_arrival = flights[-1].get('arrival_airport', '')

    if last_arrival != origin:
        return last_arrival

    # Round-trip: find first long stop
    for i in range(len(flights) - 1):
        arr_dt = _dt_from_iso(flights[i].get('arrival_datetime', ''))
        dep_dt = _dt_from_iso(flights[i + 1].get('departure_datetime', ''))
        if arr_dt and dep_dt:
            gap = dep_dt - arr_dt
            arr_airport = flights[i].get('arrival_airport', '')
            if gap >= _CONNECTION_THRESHOLD and arr_airport != origin:
                return arr_airport

    mid = (len(flights) - 1) // 2
    arr = flights[mid].get('arrival_airport', '')
    return arr if arr != origin else (flights[0].get('arrival_airport', '') or origin)


def _get_city_for_airport(airport_code: str) -> str:
    """Look up city name for an airport code from the airports table."""
    try:
        with db_conn() as conn:
            row = conn.execute(
                'SELECT city_name FROM airports WHERE iata_code = ?', (airport_code,)
            ).fetchone()
            if row and row['city_name']:
                return row['city_name']
    except Exception:
        pass
    return airport_code


def _build_trip_name(flights: list[dict], booking_ref: str = '') -> str:
    """Build a human-readable trip name."""
    if not flights:
        return 'Unknown Trip'

    sorted_flights = sorted(flights, key=lambda f: f.get('departure_datetime', ''))
    first = sorted_flights[0]
    origin = first.get('departure_airport', '')
    destination = _find_trip_destination(sorted_flights, origin)

    origin_city = _get_city_for_airport(origin) if origin else origin
    dest_city = _get_city_for_airport(destination) if destination else destination

    dep_dt_str = first.get('departure_datetime', '')
    dep_dt = _dt_from_iso(dep_dt_str)
    date_str = dep_dt.strftime('%b %Y') if dep_dt else ''

    if origin_city and dest_city and origin_city != dest_city:
        name = f"{origin_city} → {dest_city} ({date_str})" if date_str else f"{origin_city} → {dest_city}"
    elif dest_city:
        name = f"{dest_city} {date_str}".strip() if date_str else dest_city
    else:
        name = date_str or 'Trip'

    return name


def _create_trip_for_flights(flights: list[dict], booking_ref: str = '',
                              user_id: int | None = None) -> str | None:
    """Create a trip row and assign flights to it. Returns the new trip_id."""
    if not flights:
        return None

    sorted_flights = sorted(flights, key=lambda f: f.get('departure_datetime', ''))
    first = sorted_flights[0]
    last = sorted_flights[-1]

    name = _build_trip_name(sorted_flights, booking_ref)

    refs = list({f.get('booking_reference', '') for f in flights if f.get('booking_reference', '')})
    start_date = (first.get('departure_datetime', '') or '')[:10]
    end_date = (last.get('arrival_datetime', '') or last.get('departure_datetime', '') or '')[:10]
    origin = first.get('departure_airport', '')
    destination = _find_trip_destination(sorted_flights, origin)
    now = now_iso()
    trip_id = str(uuid.uuid4())

    # Use user_id from the flights if not explicitly passed
    effective_user_id = user_id
    if effective_user_id is None and flights:
        effective_user_id = flights[0].get('user_id')

    try:
        with db_write() as conn:
            conn.execute(
                '''INSERT INTO trips (id, name, booking_refs, start_date, end_date,
                   origin_airport, destination_airport, is_auto_generated, user_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)''',
                (trip_id, name, json.dumps(refs), start_date, end_date,
                 origin, destination, effective_user_id, now, now),
            )
            flight_ids = [f['id'] for f in flights]
            conn.executemany(
                'UPDATE flights SET trip_id = ?, updated_at = ? WHERE id = ?',
                [(trip_id, now, fid) for fid in flight_ids],
            )
        logger.info("Created trip '%s' (id=%s) with %d flights", name, trip_id, len(flights))
        return trip_id
    except Exception as e:
        logger.error("Error creating trip: %s", e)
        return None


def _group_by_proximity(flights: list[dict], max_gap: timedelta) -> list[list[dict]]:
    """
    Group flights by time proximity.
    Flights where the next departure is within max_gap of the previous arrival
    are considered part of the same trip.
    """
    if not flights:
        return []

    groups: list[list[dict]] = []
    current_group = [flights[0]]

    for i in range(1, len(flights)):
        prev = flights[i - 1]
        curr = flights[i]
        prev_arr = _dt_from_iso(prev.get('arrival_datetime', ''))
        curr_dep = _dt_from_iso(curr.get('departure_datetime', ''))

        if prev_arr and curr_dep and (curr_dep - prev_arr) <= max_gap:
            current_group.append(curr)
        else:
            groups.append(current_group)
            current_group = [curr]

    groups.append(current_group)
    return groups


def _merge_overlapping_groups(max_gap: timedelta, user_id: int | None = None) -> int:
    """
    Merge auto-generated trip groups whose flights overlap or are within max_gap.
    Returns the number of merges performed.
    """
    merges = 0
    changed = True

    while changed:
        changed = False

        with db_conn() as conn:
            if user_id is not None:
                trips = conn.execute(
                    'SELECT id, name FROM trips WHERE is_auto_generated = 1 AND user_id = ? ORDER BY start_date',
                    (user_id,)
                ).fetchall()
            else:
                trips = conn.execute(
                    'SELECT id, name FROM trips WHERE is_auto_generated = 1 ORDER BY start_date'
                ).fetchall()
            trip_list = [dict(t) for t in trips]

        # Load flights for each trip
        trip_flights: dict[str, list[dict]] = {}
        for trip in trip_list:
            with db_conn() as conn:
                rows = conn.execute(
                    'SELECT * FROM flights WHERE trip_id = ? ORDER BY departure_datetime',
                    (trip['id'],)
                ).fetchall()
                trip_flights[trip['id']] = [dict(r) for r in rows]

        for i, g1 in enumerate(trip_list):
            g1_flights = trip_flights.get(g1['id'], [])
            if not g1_flights:
                continue
            g1_start = _dt_from_iso(g1_flights[0].get('departure_datetime', ''))
            g1_end = _dt_from_iso(g1_flights[-1].get('arrival_datetime', '') or g1_flights[-1].get('departure_datetime', ''))

            for g2 in trip_list[i + 1:]:
                g2_flights = trip_flights.get(g2['id'], [])
                if not g2_flights:
                    continue
                g2_start = _dt_from_iso(g2_flights[0].get('departure_datetime', ''))
                g2_end = _dt_from_iso(g2_flights[-1].get('arrival_datetime', '') or g2_flights[-1].get('departure_datetime', ''))

                if not all([g1_start, g1_end, g2_start, g2_end]):
                    continue

                overlap = (
                    g1_start <= g2_end + max_gap and g2_start <= g1_end + max_gap
                )
                if overlap:
                    # Merge g2 into g1
                    now = now_iso()
                    all_flights = sorted(g1_flights + g2_flights, key=lambda f: f.get('departure_datetime', ''))
                    refs = list({f.get('booking_reference', '') for f in all_flights if f.get('booking_reference', '')})
                    new_name = _build_trip_name(all_flights)
                    new_start = (all_flights[0].get('departure_datetime', '') or '')[:10]
                    last_f = all_flights[-1]
                    new_end = (last_f.get('arrival_datetime', '') or last_f.get('departure_datetime', '') or '')[:10]
                    origin = all_flights[0].get('departure_airport', '')
                    destination = _find_trip_destination(all_flights, origin)

                    with db_write() as conn:
                        conn.execute(
                            'UPDATE flights SET trip_id = ?, updated_at = ? WHERE trip_id = ?',
                            (g1['id'], now, g2['id']),
                        )
                        conn.execute(
                            '''UPDATE trips SET name = ?, booking_refs = ?, start_date = ?,
                               end_date = ?, origin_airport = ?, destination_airport = ?,
                               updated_at = ? WHERE id = ?''',
                            (new_name, json.dumps(refs), new_start, new_end,
                             origin, destination, now, g1['id']),
                        )
                        conn.execute('DELETE FROM trips WHERE id = ?', (g2['id'],))

                    logger.info("Merged trip '%s' into '%s'", g2['name'], g1['name'])
                    merges += 1
                    changed = True
                    break

            if changed:
                break

    return merges


def regroup_all_flights(user_id: int | None = None) -> dict:
    """
    Unassign all auto-generated trips and re-run grouping from scratch.
    Manually added flights and manually created trips are preserved.
    """
    now = now_iso()
    with db_write() as conn:
        if user_id is not None:
            # Unlink flights from auto-generated trips for this user
            conn.execute(
                '''UPDATE flights SET trip_id = NULL, updated_at = ?
                   WHERE trip_id IN (SELECT id FROM trips WHERE is_auto_generated = 1 AND user_id = ?)
                   AND user_id = ?''',
                (now, user_id, user_id),
            )
            conn.execute('DELETE FROM trips WHERE is_auto_generated = 1 AND user_id = ?', (user_id,))
        else:
            conn.execute(
                '''UPDATE flights SET trip_id = NULL, updated_at = ?
                   WHERE trip_id IN (SELECT id FROM trips WHERE is_auto_generated = 1)''',
                (now,),
            )
            conn.execute('DELETE FROM trips WHERE is_auto_generated = 1')

    return auto_group_flights(user_id=user_id)
