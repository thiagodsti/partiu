"""
Trip sharing and trusted users API routes.

  POST   /api/trips/{trip_id}/share              — invite a user to a trip
  GET    /api/trips/invitations                  — list pending invitations for current user
  POST   /api/trips/invitations/{share_id}/accept
  POST   /api/trips/invitations/{share_id}/reject
  DELETE /api/trips/{trip_id}/shares/{shared_user_id}
  GET    /api/trips/{trip_id}/shares             — list accepted shares for a trip
  GET    /api/settings/trusted-users
  POST   /api/settings/trusted-users
  DELETE /api/settings/trusted-users/{trusted_user_id}
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import is_trip_owner
from ..utils import now_iso

logger = logging.getLogger(__name__)

# Use no prefix — routes are declared with full paths to avoid conflicts
# with the trips router's prefix (/api/trips).
router = APIRouter(tags=["shares"])


# ---------------------------------------------------------------------------
# Invite a user to a trip
# ---------------------------------------------------------------------------


class ShareInviteBody(BaseModel):
    username: str


@router.post("/api/trips/{trip_id}/share", status_code=201)
def share_trip(
    trip_id: str,
    body: ShareInviteBody,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    with db_conn() as conn:
        if not is_trip_owner(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")

        invitee = conn.execute(
            "SELECT id, username FROM users WHERE username = ?", (body.username,)
        ).fetchone()
        if not invitee:
            raise HTTPException(status_code=404, detail="User not found")

        if invitee["id"] == user["id"]:
            raise HTTPException(status_code=400, detail="Cannot share a trip with yourself")

        existing = conn.execute(
            "SELECT id, status FROM trip_shares WHERE trip_id = ? AND user_id = ?",
            (trip_id, invitee["id"]),
        ).fetchone()
        if existing:
            if existing["status"] == "accepted":
                raise HTTPException(status_code=400, detail="User already has access")
            # Re-invite: reset to pending
            with db_write() as wconn:
                wconn.execute(
                    "UPDATE trip_shares SET status = 'pending', invited_by = ?, updated_at = ? WHERE id = ?",
                    (user["id"], now_iso(), existing["id"]),
                )
            return {"ok": True}

        # Check if invitee trusts the caller → auto-accept
        trust = conn.execute(
            "SELECT 1 FROM trusted_users WHERE owner_id = ? AND trusted_user_id = ?",
            (invitee["id"], user["id"]),
        ).fetchone()
        initial_status = "accepted" if trust else "pending"

    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trip_id, invitee["id"], user["id"], initial_status, now_iso(), now_iso()),
        )

    return {"ok": True, "status": initial_status}


# ---------------------------------------------------------------------------
# List pending invitations for current user
# IMPORTANT: this literal route must be declared BEFORE /{trip_id}/... routes
# ---------------------------------------------------------------------------


@router.get("/api/trips/invitations")
def list_invitations(user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT ts.id, ts.trip_id, t.name AS trip_name,
                      u.username AS invited_by_username, ts.created_at
               FROM trip_shares ts
               JOIN trips t ON t.id = ts.trip_id
               JOIN users u ON u.id = ts.invited_by
               WHERE ts.user_id = ? AND ts.status = 'pending'
               ORDER BY ts.created_at DESC""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/trips/invitations/{share_id}/accept")
def accept_invitation(share_id: int, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM trip_shares WHERE id = ? AND user_id = ? AND status = 'pending'",
            (share_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invitation not found")

    with db_write() as conn:
        conn.execute(
            "UPDATE trip_shares SET status = 'accepted', updated_at = ? WHERE id = ?",
            (now_iso(), share_id),
        )
    return {"ok": True}


@router.post("/api/trips/invitations/{share_id}/reject")
def reject_invitation(share_id: int, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM trip_shares WHERE id = ? AND user_id = ? AND status = 'pending'",
            (share_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invitation not found")

    with db_write() as conn:
        conn.execute(
            "UPDATE trip_shares SET status = 'rejected', updated_at = ? WHERE id = ?",
            (now_iso(), share_id),
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# List / revoke shares on a trip (owner only)
# ---------------------------------------------------------------------------


@router.get("/api/trips/{trip_id}/shares")
def list_trip_shares(trip_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not is_trip_owner(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")

        rows = conn.execute(
            """SELECT ts.id, ts.user_id, u.username, ts.status, ts.created_at
               FROM trip_shares ts
               JOIN users u ON u.id = ts.user_id
               WHERE ts.trip_id = ? AND ts.status IN ('pending', 'accepted')
               ORDER BY ts.created_at ASC""",
            (trip_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/api/trips/{trip_id}/shares/{shared_user_id}", status_code=204)
def revoke_trip_share(trip_id: str, shared_user_id: int, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        if not is_trip_owner(trip_id, user["id"], conn):
            raise HTTPException(status_code=404, detail="Trip not found")

    with db_write() as conn:
        conn.execute(
            "DELETE FROM trip_shares WHERE trip_id = ? AND user_id = ?",
            (trip_id, shared_user_id),
        )


# ---------------------------------------------------------------------------
# Leave a shared trip (collaborator removes themselves)
# ---------------------------------------------------------------------------


@router.delete("/api/trips/{trip_id}/leave", status_code=204)
def leave_trip(trip_id: str, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM trip_shares WHERE trip_id = ? AND user_id = ? AND status IN ('pending', 'accepted')",
            (trip_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Shared trip not found")

    with db_write() as conn:
        conn.execute(
            "DELETE FROM trip_shares WHERE trip_id = ? AND user_id = ?",
            (trip_id, user["id"]),
        )


# ---------------------------------------------------------------------------
# Trusted users
# ---------------------------------------------------------------------------


class TrustedUserBody(BaseModel):
    username: str


@router.get("/api/settings/trusted-users")
def list_trusted_users(user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT u.id AS user_id, u.username, tu.created_at
               FROM trusted_users tu
               JOIN users u ON u.id = tu.trusted_user_id
               WHERE tu.owner_id = ?
               ORDER BY tu.created_at ASC""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/settings/trusted-users", status_code=201)
def add_trusted_user(body: TrustedUserBody, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        target = conn.execute(
            "SELECT id FROM users WHERE username = ?", (body.username,)
        ).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot trust yourself")

    with db_write() as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO trusted_users (owner_id, trusted_user_id, created_at) VALUES (?, ?, ?)",
                (user["id"], target["id"], now_iso()),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True}


@router.delete("/api/settings/trusted-users/{trusted_user_id}", status_code=204)
def remove_trusted_user(trusted_user_id: int, user: dict = Depends(get_current_user)):
    with db_write() as conn:
        conn.execute(
            "DELETE FROM trusted_users WHERE owner_id = ? AND trusted_user_id = ?",
            (user["id"], trusted_user_id),
        )
