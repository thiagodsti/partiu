"""
Trip day notes API routes.

  GET    /api/trips/{trip_id}/day-notes         — list all notes for a trip
  PATCH  /api/trips/{trip_id}/day-notes/{date}  — upsert note for a date (YYYY-MM-DD)
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import can_access_trip
from ..utils import now_iso

logger = logging.getLogger(__name__)
router = APIRouter(tags=["day_notes"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/api/trips/{trip_id}/day-notes")
def list_day_notes(trip_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        rows = conn.execute(
            """SELECT dn.date, dn.content, dn.updated_at, u.username AS updated_by_username
               FROM trip_day_notes dn
               LEFT JOIN users u ON u.id = dn.updated_by
               WHERE dn.trip_id = ?
               ORDER BY dn.date ASC""",
            (trip_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class DayNoteBody(BaseModel):
    content: str


@router.patch("/api/trips/{trip_id}/day-notes/{date}", status_code=200)
def upsert_day_note(
    trip_id: str,
    date: str,
    body: DayNoteBody,
    user: dict = Depends(get_current_user),
):
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="Invalid date format, expected YYYY-MM-DD")

    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")

    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_day_notes (trip_id, date, content, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(trip_id, date) DO UPDATE SET
                   content = excluded.content,
                   updated_at = excluded.updated_at,
                   updated_by = excluded.updated_by""",
            (trip_id, date, body.content, now_iso(), user["id"]),
        )
    return {"ok": True}
