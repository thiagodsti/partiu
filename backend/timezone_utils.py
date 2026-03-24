"""
Airport timezone lookup and local→UTC conversion.

Uses the airports table (lat/lon) + timezonefinder to determine the correct
IANA timezone for an airport, then converts naive local datetimes to UTC.
"""
import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import overload

logger = logging.getLogger(__name__)

# Cache up to 1000 airport timezones in memory
@lru_cache(maxsize=1000)
def _get_airport_timezone(iata_code: str) -> str | None:
    """Return the IANA timezone string for an airport IATA code, or None."""
    try:
        from .database import db_conn
        with db_conn() as conn:
            row = conn.execute(
                'SELECT latitude, longitude FROM airports WHERE iata_code = ?',
                (iata_code.upper(),)
            ).fetchone()
        if not row or row['latitude'] is None or row['longitude'] is None:
            return None

        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        tz_name = tf.timezone_at(lat=row['latitude'], lng=row['longitude'])
        return tz_name
    except Exception as e:
        logger.debug("Could not get timezone for %s: %s", iata_code, e)
        return None


@overload
def localize_to_utc(naive_dt: None, airport_iata: str) -> None: ...
@overload
def localize_to_utc(naive_dt: datetime, airport_iata: str) -> datetime: ...
def localize_to_utc(naive_dt: datetime | None, airport_iata: str) -> datetime | None:
    """
    Given a naive datetime representing local time at an airport,
    return the equivalent UTC datetime.

    Falls back to treating as UTC if timezone lookup fails.
    """
    if naive_dt is None:
        return None

    # Already timezone-aware — convert to UTC
    if naive_dt.tzinfo is not None:
        return naive_dt.astimezone(UTC)

    tz_name = _get_airport_timezone(airport_iata)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(tz_name)
            aware = naive_dt.replace(tzinfo=local_tz)
            return aware.astimezone(UTC)
        except Exception as e:
            logger.debug("Timezone conversion failed for %s (%s): %s", airport_iata, tz_name, e)

    # Fallback: treat as UTC (better than crashing)
    return naive_dt.replace(tzinfo=UTC)


def get_airport_timezone_name(iata_code: str) -> str | None:
    """Return the IANA timezone name for an airport, e.g. 'America/Sao_Paulo'."""
    return _get_airport_timezone(iata_code)


def apply_airport_timezones(flight_data: dict) -> dict:
    """
    Fix departure_datetime and arrival_datetime in a flight dict by converting
    from local airport time to UTC.
    Returns a new dict with corrected datetimes.
    """
    # Proportional-distribution paths pre-compute in real UTC and set this flag.
    # We only need to add the timezone name strings, not re-convert the datetimes.
    if flight_data.get('_times_already_utc'):
        result = dict(flight_data)
        result.pop('_times_already_utc', None)
        dep_airport = flight_data.get('departure_airport', '')
        arr_airport = flight_data.get('arrival_airport', '')
        if dep_airport:
            result['departure_timezone'] = _get_airport_timezone(dep_airport)
        if arr_airport:
            result['arrival_timezone'] = _get_airport_timezone(arr_airport)
        return result

    dep_airport = flight_data.get('departure_airport', '')
    arr_airport = flight_data.get('arrival_airport', '')

    dep_dt = flight_data.get('departure_datetime')
    arr_dt = flight_data.get('arrival_datetime')

    # Strip UTC tzinfo if it was incorrectly applied by _make_aware()
    # (i.e., the time is actually local time mislabelled as UTC)
    if dep_dt and dep_dt.tzinfo == UTC:
        dep_dt = dep_dt.replace(tzinfo=None)
    if arr_dt and arr_dt.tzinfo == UTC:
        arr_dt = arr_dt.replace(tzinfo=None)

    result = dict(flight_data)
    if dep_dt and dep_airport:
        result['departure_datetime'] = localize_to_utc(dep_dt, dep_airport)
        result['departure_timezone'] = _get_airport_timezone(dep_airport)
    if arr_dt and arr_airport:
        result['arrival_datetime'] = localize_to_utc(arr_dt, arr_airport)
        result['arrival_timezone'] = _get_airport_timezone(arr_airport)

    return result
