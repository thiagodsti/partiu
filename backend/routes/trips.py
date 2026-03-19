"""
Trip CRUD routes.
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..trip_images import fetch_trip_image, trip_image_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trips", tags=["trips"])


def _now_iso():
    return datetime.now(UTC).isoformat()


def _row_to_trip(row) -> dict:
    d = dict(row)
    # Parse booking_refs JSON
    try:
        d["booking_refs"] = json.loads(d.get("booking_refs") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["booking_refs"] = []
    return d


@router.get("")
def list_trips(user: dict = Depends(get_current_user)):
    """Return all trips ordered by start_date descending."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trips WHERE user_id = ? ORDER BY start_date ASC", (user["id"],)
        ).fetchall()
        trips = [_row_to_trip(r) for r in rows]

        # Attach flight counts
        for trip in trips:
            count = conn.execute(
                "SELECT COUNT(*) FROM flights WHERE trip_id = ? AND user_id = ?",
                (trip["id"], user["id"]),
            ).fetchone()[0]
            trip["flight_count"] = count

    return {"trips": trips}


@router.get("/{trip_id}")
def get_trip(trip_id: str, user: dict = Depends(get_current_user)):
    """Return a single trip with its flights."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trip not found")
        trip = _row_to_trip(row)

        flights = conn.execute(
            "SELECT * FROM flights WHERE trip_id = ? AND user_id = ? ORDER BY departure_datetime",
            (trip_id, user["id"]),
        ).fetchall()
        trip["flights"] = [dict(f) for f in flights]

    return trip


class TripCreate(BaseModel):
    name: str
    booking_refs: list[str] = []
    start_date: str = ""
    end_date: str = ""
    origin_airport: str = ""
    destination_airport: str = ""


class TripUpdate(BaseModel):
    name: str | None = None
    booking_refs: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    origin_airport: str | None = None
    destination_airport: str | None = None


@router.post("", status_code=201)
def create_trip(body: TripCreate, user: dict = Depends(get_current_user)):
    """Create a new trip manually."""
    now = _now_iso()
    trip_id = str(uuid.uuid4())

    with db_write() as conn:
        conn.execute(
            """INSERT INTO trips (id, name, booking_refs, start_date, end_date,
               origin_airport, destination_airport, is_auto_generated, user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                trip_id,
                body.name,
                json.dumps(body.booking_refs),
                body.start_date,
                body.end_date,
                body.origin_airport,
                body.destination_airport,
                user["id"],
                now,
                now,
            ),
        )

    return {"id": trip_id, "name": body.name}


@router.patch("/{trip_id}")
def update_trip(trip_id: str, body: TripUpdate, user: dict = Depends(get_current_user)):
    """Update trip fields."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trip not found")

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.booking_refs is not None:
        updates["booking_refs"] = json.dumps(body.booking_refs)
    if body.start_date is not None:
        updates["start_date"] = body.start_date
    if body.end_date is not None:
        updates["end_date"] = body.end_date
    if body.origin_airport is not None:
        updates["origin_airport"] = body.origin_airport
    if body.destination_airport is not None:
        updates["destination_airport"] = body.destination_airport

    if not updates:
        return {"id": trip_id}

    updates["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [trip_id, user["id"]]

    with db_write() as conn:
        conn.execute(f"UPDATE trips SET {set_clause} WHERE id = ? AND user_id = ?", values)

    return {"id": trip_id}


@router.delete("/{trip_id}", status_code=204)
def delete_trip(trip_id: str, user: dict = Depends(get_current_user)):
    """Delete a trip (flights are unlinked, not deleted)."""
    now = _now_iso()
    with db_write() as conn:
        conn.execute(
            "UPDATE flights SET trip_id = NULL, updated_at = ? WHERE trip_id = ? AND user_id = ?",
            (now, trip_id, user["id"]),
        )
        conn.execute("DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"]))


@router.post("/{trip_id}/flights/{flight_id}")
def add_flight_to_trip(trip_id: str, flight_id: str, user: dict = Depends(get_current_user)):
    """Assign a flight to a trip."""
    now = _now_iso()
    with db_write() as conn:
        # Verify trip and flight exist and belong to this user
        if not conn.execute(
            "SELECT id FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"])
        ).fetchone():
            raise HTTPException(status_code=404, detail="Trip not found")
        if not conn.execute(
            "SELECT id FROM flights WHERE id = ? AND user_id = ?", (flight_id, user["id"])
        ).fetchone():
            raise HTTPException(status_code=404, detail="Flight not found")

        conn.execute(
            "UPDATE flights SET trip_id = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (trip_id, now, flight_id, user["id"]),
        )
    return {"ok": True}


@router.delete("/{trip_id}/flights/{flight_id}")
def remove_flight_from_trip(trip_id: str, flight_id: str, user: dict = Depends(get_current_user)):
    """Unlink a flight from a trip."""
    now = _now_iso()
    with db_write() as conn:
        conn.execute(
            "UPDATE flights SET trip_id = NULL, updated_at = ? WHERE id = ? AND trip_id = ? AND user_id = ?",
            (now, flight_id, trip_id, user["id"]),
        )
    return {"ok": True}


def _get_trip_city(trip_id: str, user_id: int) -> str | None:
    """Look up the destination city for a trip via its destination_airport."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT destination_airport FROM trips WHERE id = ? AND user_id = ?",
            (trip_id, user_id),
        ).fetchone()
        if not row or not row["destination_airport"]:
            # Fall back to the arrival airport of the last flight in the trip
            row2 = conn.execute(
                "SELECT arrival_airport FROM flights WHERE trip_id = ? AND user_id = ? "
                "ORDER BY departure_datetime DESC LIMIT 1",
                (trip_id, user_id),
            ).fetchone()
            iata = row2["arrival_airport"] if row2 else None
        else:
            iata = row["destination_airport"]

        if not iata:
            return None

        airport = conn.execute(
            "SELECT city_name FROM airports WHERE iata_code = ?", (iata.upper(),)
        ).fetchone()
        city = airport["city_name"] if airport and airport["city_name"] else iata
        # Strip parenthetical suffix (e.g. "Paris (Roissy-en-France)" → "Paris")
        # then strip region/state suffix (e.g. "London, Essex" → "London")
        if city:
            city = city.split("(")[0].split(",")[0].strip()
        return city or iata


@router.get("/{trip_id}/image")
async def get_trip_image(trip_id: str, user: dict = Depends(get_current_user)):
    """Return the cached destination photo for this trip, fetching it on first request."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT image_fetched_at FROM trips WHERE id = ? AND user_id = ?",
            (trip_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")

    cached = trip_image_path(trip_id)
    if cached.exists():
        return FileResponse(
            str(cached), media_type="image/jpeg", headers={"Cache-Control": "no-cache"}
        )

    # Already attempted and failed — don't hammer Wikipedia on every request
    if row["image_fetched_at"]:
        raise HTTPException(status_code=404, detail="No image available")

    city_name = _get_trip_city(trip_id, user["id"])
    if not city_name:
        raise HTTPException(status_code=404, detail="No destination city found")

    success = await fetch_trip_image(trip_id, city_name)

    with db_write() as conn:
        conn.execute(
            "UPDATE trips SET image_fetched_at = ? WHERE id = ? AND user_id = ?",
            (datetime.now(UTC).isoformat(), trip_id, user["id"]),
        )

    if success and cached.exists():
        return FileResponse(
            str(cached), media_type="image/jpeg", headers={"Cache-Control": "no-cache"}
        )

    raise HTTPException(status_code=404, detail="No image available")


@router.get("/{trip_id}/immich-album/status")
async def check_immich_album(trip_id: str, user: dict = Depends(get_current_user)):
    """Check whether the stored Immich album still exists. Clears the DB entry if it was deleted."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip = _row_to_trip(row)

    album_id = trip.get("immich_album_id")
    if not album_id:
        return {"album_id": None, "exists": False}

    with db_conn() as conn:
        u = conn.execute(
            "SELECT immich_url, immich_api_key FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
    immich_url = (u["immich_url"] or "").strip() if u else ""
    immich_api_key = (u["immich_api_key"] or "").strip() if u else ""

    if not immich_url or not immich_api_key:
        return {"album_id": album_id, "exists": True}  # can't check — assume it exists

    from ..immich import album_exists

    exists = await album_exists(immich_url, immich_api_key, album_id)
    # Don't modify DB here — let the create endpoint handle cleanup.
    # Only update frontend local state via the response.
    return {"album_id": album_id if exists else None, "exists": exists}


@router.post("/{trip_id}/immich-album")
async def create_immich_album(trip_id: str, user: dict = Depends(get_current_user)):
    """Create an Immich album with photos from this trip's date range, or return the existing one."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")
    trip = _row_to_trip(row)

    if not trip.get("start_date") or not trip.get("end_date"):
        raise HTTPException(
            status_code=400, detail="Trip must have start and end dates to create an album"
        )

    with db_conn() as conn:
        u = conn.execute(
            "SELECT immich_url, immich_api_key FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
    immich_url = (u["immich_url"] or "").strip() if u else ""
    immich_api_key = (u["immich_api_key"] or "").strip() if u else ""

    # If an album ID is stored, verify it still exists in Immich before returning the cached link
    if trip.get("immich_album_id") and immich_url and immich_api_key:
        from ..immich import album_exists

        if await album_exists(immich_url, immich_api_key, trip["immich_album_id"]):
            base = immich_url.rstrip("/")
            album_url = f"{base}/albums/{trip['immich_album_id']}"
            return {
                "album_id": trip["immich_album_id"],
                "album_url": album_url,
                "asset_count": None,
                "already_exists": True,
            }
        # Album was deleted in Immich — clear the stored ID and recreate below
        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET immich_album_id = NULL, updated_at = ? WHERE id = ? AND user_id = ?",
                (_now_iso(), trip_id, user["id"]),
            )

    if not immich_url or not immich_api_key:
        raise HTTPException(
            status_code=400,
            detail="Immich is not configured. Add your Immich URL and API key in Settings.",
        )

    from ..immich import create_trip_album

    try:
        result = await create_trip_album(
            base_url=immich_url,
            api_key=immich_api_key,
            album_name=trip["name"],
            start_date=trip["start_date"],
            end_date=trip["end_date"],
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error("Immich album creation failed for trip %s: %s", trip_id, e)
        raise HTTPException(status_code=502, detail=f"Immich error: {e}")

    with db_write() as conn:
        conn.execute(
            "UPDATE trips SET immich_album_id = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (result["album_id"], _now_iso(), trip_id, user["id"]),
        )

    return {
        "album_id": result["album_id"],
        "album_url": result["album_url"],
        "asset_count": result["asset_count"],
        "already_exists": False,
    }


@router.post("/{trip_id}/image/refresh")
async def refresh_trip_image(trip_id: str, user: dict = Depends(get_current_user)):
    """Delete the current image and fetch a different random one."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM trips WHERE id = ? AND user_id = ?", (trip_id, user["id"])
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")

    city_name = _get_trip_city(trip_id, user["id"])
    if not city_name:
        raise HTTPException(status_code=404, detail="No destination city found")

    success = await fetch_trip_image(trip_id, city_name, force_refresh=True)

    with db_write() as conn:
        conn.execute(
            "UPDATE trips SET image_fetched_at = ? WHERE id = ? AND user_id = ?",
            (datetime.now(UTC).isoformat(), trip_id, user["id"]),
        )

    if success and trip_image_path(trip_id).exists():
        return {"ok": True}

    raise HTTPException(status_code=404, detail="No image available")
