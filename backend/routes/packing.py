"""
Trip packing list API routes.

  GET    /api/trips/{trip_id}/packing                       — list all items
  POST   /api/trips/{trip_id}/packing                       — create item
  PATCH  /api/trips/{trip_id}/packing/{item_id}             — update item (text, checked)
  DELETE /api/trips/{trip_id}/packing/{item_id}             — delete item
  POST   /api/trips/{trip_id}/packing/clear-checked         — bulk-delete checked items
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import can_access_trip
from ..utils import now_iso

router = APIRouter(tags=["packing"])


@router.get("/api/trips/{trip_id}/packing")
def list_items(trip_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        rows = conn.execute(
            """SELECT id, trip_id, text, checked, sort_order, created_by, created_at
               FROM packing_items
               WHERE trip_id = ?
               ORDER BY sort_order ASC, created_at ASC""",
            (trip_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class PackingItemBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class PackingItemUpdateBody(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    checked: bool | None = None


@router.post("/api/trips/{trip_id}/packing", status_code=201)
def create_item(trip_id: str, body: PackingItemBody, user: dict = Depends(get_current_user)):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Item text cannot be empty")

    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM packing_items WHERE trip_id = ?",
            (trip_id,),
        ).fetchone()[0]

    item_id = str(uuid.uuid4())
    with db_write() as conn:
        conn.execute(
            """INSERT INTO packing_items (id, trip_id, text, checked, sort_order, created_by, created_at)
               VALUES (?, ?, ?, 0, ?, ?, ?)""",
            (item_id, trip_id, body.text.strip(), max_order + 1, user["id"], now_iso()),
        )
    return {"id": item_id, "ok": True}


@router.patch("/api/trips/{trip_id}/packing/{item_id}")
def update_item(
    trip_id: str,
    item_id: str,
    body: PackingItemUpdateBody,
    user: dict = Depends(get_current_user),
):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        item = conn.execute(
            "SELECT id FROM packing_items WHERE id = ? AND trip_id = ?",
            (item_id, trip_id),
        ).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    updates: dict = {}
    if body.text is not None:
        if not body.text.strip():
            raise HTTPException(status_code=400, detail="Item text cannot be empty")
        updates["text"] = body.text.strip()
    if body.checked is not None:
        updates["checked"] = 1 if body.checked else 0

    if not updates:
        return {"ok": True}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db_write() as conn:
        conn.execute(
            f"UPDATE packing_items SET {set_clause} WHERE id = ? AND trip_id = ?",
            list(updates.values()) + [item_id, trip_id],
        )
    return {"ok": True}


@router.delete("/api/trips/{trip_id}/packing/{item_id}", status_code=204)
def delete_item(trip_id: str, item_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")
        item = conn.execute(
            "SELECT id FROM packing_items WHERE id = ? AND trip_id = ?",
            (item_id, trip_id),
        ).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    with db_write() as conn:
        conn.execute(
            "DELETE FROM packing_items WHERE id = ? AND trip_id = ?",
            (item_id, trip_id),
        )
    return None


@router.post("/api/trips/{trip_id}/packing/clear-checked", status_code=204)
def clear_checked(trip_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not can_access_trip(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")

    with db_write() as conn:
        conn.execute(
            "DELETE FROM packing_items WHERE trip_id = ? AND checked = 1",
            (trip_id,),
        )
    return None
