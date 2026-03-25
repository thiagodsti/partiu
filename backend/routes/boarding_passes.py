"""
Boarding passes API routes.

  GET    /api/flights/{flight_id}/boarding-passes        — list all for a flight
  POST   /api/flights/{flight_id}/boarding-passes        — manual upload
  GET    /api/boarding-passes/{bp_id}/image              — serve image file
  DELETE /api/boarding-passes/{bp_id}                    — delete
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import can_access_flight
from ..utils import now_iso

router = APIRouter(tags=["boarding-passes"])

_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _get_storage_dir() -> Path:
    from ..config import settings

    bp_dir = Path(settings.DB_PATH).parent / "boarding_passes"
    bp_dir.mkdir(parents=True, exist_ok=True)
    return bp_dir


def _flight_belongs_to_user(flight_id: str, user_id: int) -> bool:
    """Read access: owner or accepted collaborator."""
    with db_conn() as conn:
        return can_access_flight(flight_id, user_id, conn)


def _flight_owned_by_user(flight_id: str, user_id: int) -> bool:
    """Write access: owner only."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM flights WHERE id = ? AND user_id = ?", (flight_id, user_id)
        ).fetchone()
    return row is not None


def _bp_belongs_to_user(bp_id: str, user_id: int) -> dict | None:
    """Return the boarding pass row if user has read access (owner or collaborator)."""
    with db_conn() as conn:
        # First get the bp row
        bp_row = conn.execute(
            "SELECT bp.* FROM boarding_passes bp WHERE bp.id = ?",
            (bp_id,),
        ).fetchone()
        if not bp_row:
            return None
        if not can_access_flight(bp_row["flight_id"], user_id, conn):
            return None
    return dict(bp_row)


def _bp_owned_by_user(bp_id: str, user_id: int) -> dict | None:
    """Return the boarding pass row only if user owns it."""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT bp.* FROM boarding_passes bp
               JOIN flights f ON f.id = bp.flight_id
               WHERE bp.id = ? AND f.user_id = ?""",
            (bp_id, user_id),
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# List boarding passes for a flight
# ---------------------------------------------------------------------------


@router.get("/api/flights/{flight_id}/boarding-passes")
def list_boarding_passes(flight_id: str, user: dict = Depends(get_current_user)):
    if not _flight_belongs_to_user(flight_id, user["id"]):
        raise HTTPException(status_code=404, detail="Flight not found")

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM boarding_passes WHERE flight_id = ? ORDER BY source_page ASC, created_at ASC",
            (flight_id,),
        ).fetchall()

    return [
        {
            "id": r["id"],
            "flight_id": r["flight_id"],
            "passenger_name": r["passenger_name"],
            "seat": r["seat"],
            "source_page": r["source_page"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Manual upload
# ---------------------------------------------------------------------------


@router.post("/api/flights/{flight_id}/boarding-passes", status_code=201)
async def upload_boarding_pass(
    flight_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
):
    if not _flight_owned_by_user(flight_id, user["id"]):
        raise HTTPException(status_code=404, detail="Flight not found")

    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {file.content_type}. Use PNG or JPEG.",
        )

    image_bytes = await file.read()
    if len(image_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    if len(image_bytes) < 10:
        raise HTTPException(status_code=422, detail="File is empty or too small")

    bp_id = _save_boarding_pass(
        flight_id=flight_id,
        image_bytes=image_bytes,
        passenger_name=None,
        seat=None,
        source_email_id=None,
        source_page=0,
    )
    return {"id": bp_id}


# ---------------------------------------------------------------------------
# Serve image
# ---------------------------------------------------------------------------


@router.get("/api/boarding-passes/{bp_id}/image")
def get_boarding_pass_image(bp_id: str, user: dict = Depends(get_current_user)):
    bp = _bp_belongs_to_user(bp_id, user["id"])
    if not bp:
        raise HTTPException(status_code=404, detail="Boarding pass not found")

    image_path = bp.get("image_path")
    if not image_path or not Path(image_path).exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    suffix = Path(image_path).suffix.lower()
    media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return FileResponse(image_path, media_type=media_type)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/api/boarding-passes/{bp_id}", status_code=204)
def delete_boarding_pass(bp_id: str, user: dict = Depends(get_current_user)):
    bp = _bp_owned_by_user(bp_id, user["id"])
    if not bp:
        raise HTTPException(status_code=404, detail="Boarding pass not found")

    image_path = bp.get("image_path")

    with db_write() as conn:
        conn.execute("DELETE FROM boarding_passes WHERE id = ?", (bp_id,))

    # Remove image file
    if image_path:
        try:
            Path(image_path).unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Internal helper used by sync_job
# ---------------------------------------------------------------------------


def _save_boarding_pass(
    *,
    flight_id: str,
    image_bytes: bytes,
    passenger_name: str | None,
    seat: str | None,
    source_email_id: str | None,
    source_page: int,
) -> str:
    """Save a boarding pass image and insert the DB row. Returns the new id."""
    storage_dir = _get_storage_dir()
    bp_id = str(uuid.uuid4())
    image_path = str(storage_dir / f"{bp_id}.png")
    Path(image_path).write_bytes(image_bytes)

    with db_write() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO boarding_passes
               (id, flight_id, passenger_name, seat, image_path, source_email_id, source_page, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bp_id,
                flight_id,
                passenger_name or None,
                seat or None,
                image_path,
                source_email_id,
                source_page,
                now_iso(),
            ),
        )

    return bp_id
