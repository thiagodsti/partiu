"""
Trip CRUD routes.
"""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..trip_images import fetch_trip_image, trip_image_path

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
        # Strip region/state suffix (e.g. "London, Essex" → "London") for better Wikipedia results
        return city.split(",")[0].strip() if city else city


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
