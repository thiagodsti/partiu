"""
Aircraft type lookup.

Primary source: AviationStack (real-time, 100 req/month free tier).
Fallback:       OpenSky Network (real-time, no auth required, unlimited).

Both APIs only return data while a flight is airborne (or very recently landed).
The background aircraft_sync job calls this during the flight window.

Aircraft type name resolution order:
  1. Local aircraft_types table (pre-populated, fast, no API call)
  2. hexdb.io lookup by ICAO24 (free, no auth, cached into aircraft_types table)
"""

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

_AVIATIONSTACK_BASE = "http://api.aviationstack.com/v1"
_OPENSKY_BASE = "https://opensky-network.org/api"
_HEXDB_BASE = "https://hexdb.io/api/v1"
_TIMEOUT = 10.0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _lookup_type_name(iata_code: str) -> str | None:
    """Look up a human-readable aircraft name from the local aircraft_types table."""
    if not iata_code:
        return None
    from .database import db_conn

    with db_conn() as conn:
        row = conn.execute(
            "SELECT name FROM aircraft_types WHERE iata_code = ?",
            (iata_code.upper(),),
        ).fetchone()
    return row["name"] if row else None


async def _fetch_type_name_from_hexdb(icao24: str) -> tuple[str, str, str]:
    """
    Call hexdb.io to resolve ICAO24 → aircraft type name.
    Returns (type_name, iata_code, registration). Caches the result in aircraft_types table.
    """
    if not icao24:
        return "", ""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_HEXDB_BASE}/aircraft/{icao24.lower()}")
            if resp.status_code != 200:
                return "", ""
            data = resp.json()

        # hexdb.io field names: ICAOTypeCode, Manufacturer, Type (variant), Registration
        iata_code = (data.get("ICAOTypeCode") or "").strip().upper()
        manufacturer = (data.get("Manufacturer") or "").strip().title()
        variant = (data.get("Type") or "").strip()
        registration = (data.get("Registration") or "").strip()

        if not manufacturer and not iata_code:
            return "", "", registration

        # Prefer the local aircraft_types table for a clean name (e.g. "Boeing 777-300ER")
        # rather than the raw variant string from hexdb (e.g. "777 32WER")
        if iata_code:
            from .database import db_conn

            with db_conn() as conn:
                row = conn.execute(
                    "SELECT name FROM aircraft_types WHERE iata_code = ?", (iata_code,)
                ).fetchone()
            if row:
                return row["name"], iata_code, registration

        # Fall back to building name from hexdb fields
        name = f"{manufacturer} {variant}".strip() if variant else manufacturer

        # Cache it so we never call hexdb again for this type
        if iata_code and name:
            from .database import db_write

            with db_write() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO aircraft_types (iata_code, name, manufacturer) VALUES (?, ?, ?)",
                    (iata_code, name, manufacturer),
                )
            logger.debug("Cached aircraft type from hexdb: %s → %s", iata_code, name)

        return name, iata_code, registration

    except Exception as e:
        logger.debug("hexdb lookup failed for %s: %s", icao24, e)
        return "", "", ""


async def resolve_aircraft_name(iata_code: str, icao24: str) -> str:
    """
    Return a human-readable aircraft name, e.g. "Boeing 777-300ER".

    1. Check local aircraft_types table (instant, no API call).
    2. If not found, call hexdb.io with the ICAO24 and cache the result.
    3. Fall back to the raw IATA code if everything fails.
    """
    # Step 1: local table
    name = _lookup_type_name(iata_code)
    if name:
        return name

    # Step 2: hexdb.io
    if icao24:
        name, _, _reg = await _fetch_type_name_from_hexdb(icao24)
        if name:
            return name

    # Step 3: raw code (better than nothing)
    return iata_code or ""


async def _fetch_via_aviationstack(flight_number: str, api_key: str) -> dict:
    """Look up aircraft via AviationStack (consumes 1 of 100 monthly free requests)."""
    callsign = flight_number.replace(" ", "").upper()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_AVIATIONSTACK_BASE}/flights",
                params={"access_key": api_key, "flight_iata": callsign},
            )
            if resp.status_code != 200:
                logger.debug("AviationStack lookup failed: HTTP %d", resp.status_code)
                return {}

            data = resp.json()
            flights = data.get("data") or []
            if not flights:
                logger.debug("AviationStack: no data for %s", callsign)
                return {}

            f = flights[0]
            aircraft = f.get("aircraft") or {}
            departure = f.get("departure") or {}
            arrival = f.get("arrival") or {}
            return {
                "icao24": (aircraft.get("icao24") or "").upper(),
                "iata_code": (aircraft.get("iata") or "").upper(),
                "registration": aircraft.get("registration") or "",
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
        logger.debug("AviationStack error for %s: %s", callsign, e)
        return {}


async def _fetch_via_opensky(flight_number: str) -> dict:
    """Look up aircraft via OpenSky Network (free, no auth, unlimited)."""
    callsign = flight_number.replace(" ", "").upper()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_OPENSKY_BASE}/states/all",
                params={"callsign": callsign},
            )
            if resp.status_code != 200:
                logger.debug("OpenSky states lookup failed: HTTP %d", resp.status_code)
                return {}

            states = resp.json().get("states") or []
            if not states:
                logger.debug("OpenSky: no state for %s", callsign)
                return {}

            icao24 = (states[0][0] or "").upper()
            if not icao24:
                return {}

            # Try to get IATA type code from OpenSky metadata
            iata_code = ""
            meta_resp = await client.get(
                f"{_OPENSKY_BASE}/metadata/aircraft/icao/{icao24.lower()}",
            )
            if meta_resp.status_code == 200:
                meta = meta_resp.json()
                iata_code = (meta.get("typecode") or "").upper()

            return {
                "icao24": icao24,
                "iata_code": iata_code,
                "registration": "",
            }

    except httpx.TimeoutException:
        logger.debug("OpenSky timeout for %s", callsign)
        return {}
    except Exception as e:
        logger.debug("OpenSky error for %s: %s", callsign, e)
        return {}


async def fetch_aircraft_info(flight_number: str) -> dict:
    """
    Try AviationStack first (if API key configured), fall back to OpenSky.

    Returns a dict with keys: icao24, iata_code, type_name, registration.
    Returns {} if neither source has data (flight not yet airborne or already landed).
    """
    from .config import settings

    raw = {}
    if settings.AVIATIONSTACK_API_KEY:
        raw = await _fetch_via_aviationstack(flight_number, settings.AVIATIONSTACK_API_KEY)
        if raw.get("icao24") or raw.get("iata_code"):
            logger.debug("Aircraft raw info for %s from AviationStack: %s", flight_number, raw)
        else:
            raw = {}

    if not raw:
        raw = await _fetch_via_opensky(flight_number)
        if raw:
            logger.debug("Aircraft raw info for %s from OpenSky: %s", flight_number, raw)

    if not raw:
        return {}

    # Resolve human-readable name
    type_name = await resolve_aircraft_name(raw.get("iata_code", ""), raw.get("icao24", ""))

    return {
        "icao24": raw.get("icao24", ""),
        "iata_code": raw.get("iata_code", ""),
        "type_name": type_name,
        "registration": raw.get("registration", ""),
        "flight_status": raw.get("flight_status", ""),
        "departure_delay": raw.get("departure_delay"),
        "arrival_delay": raw.get("arrival_delay"),
        "departure_actual": raw.get("departure_actual", ""),
        "arrival_estimated": raw.get("arrival_estimated", ""),
    }


async def get_or_fetch_aircraft(flight_id: str, flight_number: str) -> dict:
    """Return cached aircraft info, or fetch live if not yet cached."""
    from .database import db_conn, db_write

    with db_conn() as conn:
        row = conn.execute(
            "SELECT aircraft_type, aircraft_icao, aircraft_registration, aircraft_fetched_at FROM flights WHERE id = ?",
            (flight_id,),
        ).fetchone()

    if row and row["aircraft_fetched_at"]:
        return {
            "type_name": row["aircraft_type"] or "",
            "icao24": row["aircraft_icao"] or "",
            "registration": row["aircraft_registration"] or "",
            "fetched_at": row["aircraft_fetched_at"],
        }

    info = await fetch_aircraft_info(flight_number)
    now = _now_iso()

    with db_write() as conn:
        conn.execute(
            """UPDATE flights
               SET aircraft_type = ?, aircraft_icao = ?, aircraft_registration = ?,
                   aircraft_fetched_at = ?, updated_at = ?
               WHERE id = ?""",
            (
                info.get("type_name") or "",
                info.get("icao24") or "",
                info.get("registration") or "",
                now,
                now,
                flight_id,
            ),
        )

    return {
        "type_name": info.get("type_name", ""),
        "icao24": info.get("icao24", ""),
        "registration": info.get("registration", ""),
        "fetched_at": now,
    }
