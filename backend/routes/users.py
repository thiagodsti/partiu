"""
User management routes (admin only).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..audit_log import audit
from ..auth import hash_password, require_admin
from ..database import db_conn, db_write

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    smtp_recipient_address: str | None = None


class UpdateUserRequest(BaseModel):
    is_admin: bool | None = None
    smtp_recipient_address: str | None = None
    new_password: str | None = None


@router.get("")
def list_users(admin: dict = Depends(require_admin)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, smtp_recipient_address, totp_enabled, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("")
def create_user(body: CreateUserRequest, admin: dict = Depends(require_admin)):
    username = body.username.strip().lower()
    if len(username) < 4:
        raise HTTPException(400, "Username must be at least 4 characters")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    with db_write() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, smtp_recipient_address) VALUES (?, ?, ?, ?)",
                (
                    username,
                    hash_password(body.password),
                    1 if body.is_admin else 0,
                    body.smtp_recipient_address,
                ),
            )
            user_id = cursor.lastrowid
        except Exception:
            raise HTTPException(400, "Could not create user")
    audit(
        "user_created",
        user_id=admin["id"],
        target_user_id=user_id,
        username=username,
        is_admin=body.is_admin,
    )
    return {
        "id": user_id,
        "username": username,
        "is_admin": body.is_admin,
        "smtp_recipient_address": body.smtp_recipient_address,
    }


@router.patch("/{user_id}")
def update_user(user_id: int, body: UpdateUserRequest, admin: dict = Depends(require_admin)):
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
    updates = {}
    if body.is_admin is not None:
        updates["is_admin"] = 1 if body.is_admin else 0
    if body.smtp_recipient_address is not None:
        updates["smtp_recipient_address"] = body.smtp_recipient_address
    if body.new_password is not None:
        if len(body.new_password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        updates["password_hash"] = hash_password(body.new_password)
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id = ?", list(updates.values()) + [user_id]
            )
    audit("user_updated", user_id=admin["id"], target_user_id=user_id, fields=list(updates.keys()))
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    with db_write() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    audit("user_deleted", user_id=admin["id"], target_user_id=user_id)
    return {"ok": True}
