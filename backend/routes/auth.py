"""
Authentication routes: setup, login, logout, me, change-password, 2FA.
"""

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..audit_log import audit
from ..auth import (
    create_pending_2fa_cookie,
    create_session_cookie,
    decode_pending_2fa_cookie,
    decode_session_cookie,
    get_current_user,
    has_any_users,
    hash_password,
    revoke_session_cookie,
    verify_password,
)
from ..database import db_conn, db_write
from ..limiter import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

_TOTP_LOCKOUT_THRESHOLD = 5
_TOTP_LOCKOUT_WINDOW_MINUTES = 15


class SetupRequest(BaseModel):
    username: str
    password: str
    smtp_recipient_address: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    totp_code: str | None = None


class TwoFAVerifyRequest(BaseModel):
    code: str


class TwoFAEnableRequest(BaseModel):
    code: str


class TwoFADisableRequest(BaseModel):
    code: str | None = None
    password: str | None = None


class UpdateMeRequest(BaseModel):
    locale: str | None = None

_VALID_LOCALES = {"en", "pt-BR"}


def _check_totp_lockout(user_id: int) -> None:
    """Raise HTTP 429 if the user has too many recent TOTP failures."""
    with db_conn() as conn:
        recent_failures = conn.execute(
            """SELECT COUNT(*) FROM auth_attempts
               WHERE user_id = ? AND attempt_type = 'totp' AND success = 0
               AND attempted_at > datetime('now', ?)""",
            (user_id, f"-{_TOTP_LOCKOUT_WINDOW_MINUTES} minutes"),
        ).fetchone()[0]
    if recent_failures >= _TOTP_LOCKOUT_THRESHOLD:
        raise HTTPException(429, "Too many failed 2FA attempts. Please try again later.")


def _record_totp_attempt(user_id: int, success: bool) -> None:
    with db_write() as conn:
        conn.execute(
            "INSERT INTO auth_attempts (user_id, attempt_type, success) VALUES (?, 'totp', ?)",
            (user_id, 1 if success else 0),
        )


@router.post("/setup")
@limiter.limit("5/minute")
def setup(request: Request, body: SetupRequest, response: Response):
    if has_any_users():
        raise HTTPException(409, "Setup already completed")
    if len(body.username.strip()) < 2:
        raise HTTPException(400, "Username too short")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    with db_write() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, smtp_recipient_address) VALUES (?, ?, 1, ?)",
                (body.username.strip(), hash_password(body.password), body.smtp_recipient_address),
            )
            user_id = cursor.lastrowid
            # Assign any existing orphan data to this first admin
            conn.execute("UPDATE flights SET user_id = ? WHERE user_id IS NULL", (user_id,))
            conn.execute("UPDATE trips SET user_id = ? WHERE user_id IS NULL", (user_id,))
            conn.execute(
                "UPDATE email_sync_state SET user_id = ? WHERE user_id IS NULL", (user_id,)
            )
        except Exception:
            raise HTTPException(400, "Could not create user")
    audit("setup", user_id=user_id, username=body.username.strip())
    token = create_session_cookie(user_id)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=30 * 86400,
    )
    return {
        "id": user_id,
        "username": body.username.strip(),
        "is_admin": True,
        "smtp_recipient_address": body.smtp_recipient_address,
        "totp_enabled": False,
        "locale": "en",
    }


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, response: Response):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, is_admin, smtp_recipient_address, totp_enabled, locale FROM users WHERE username = ?",
            (body.username,),
        ).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        audit(
            "login_failed",
            username=body.username,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(401, "Invalid username or password")

    if row["totp_enabled"]:
        pending_token = create_pending_2fa_cookie(row["id"])
        resp = JSONResponse({"requires_2fa": True}, status_code=200)
        resp.set_cookie(
            "pending_2fa", pending_token, httponly=True, samesite="lax", secure=True, max_age=300
        )
        return resp

    audit(
        "login",
        user_id=row["id"],
        username=row["username"],
        ip=request.client.host if request.client else None,
    )
    token = create_session_cookie(row["id"])
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=30 * 86400,
    )
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "smtp_recipient_address": row["smtp_recipient_address"],
        "totp_enabled": bool(row["totp_enabled"]),
        "locale": row["locale"] or "en",
    }


@router.post("/2fa/verify")
@limiter.limit("10/minute")
def verify_2fa(request: Request, body: TwoFAVerifyRequest, response: Response):
    pending_token = request.cookies.get("pending_2fa")
    if not pending_token:
        raise HTTPException(401, "No pending 2FA session")
    user_id = decode_pending_2fa_cookie(pending_token)
    if user_id is None:
        raise HTTPException(401, "Pending 2FA session expired or invalid")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, smtp_recipient_address, totp_secret, totp_enabled, locale FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(401, "User not found")
    if not row["totp_secret"]:
        raise HTTPException(400, "2FA not configured")

    _check_totp_lockout(user_id)

    success = pyotp.TOTP(row["totp_secret"]).verify(body.code, valid_window=1)
    _record_totp_attempt(user_id, success)

    if not success:
        audit("2fa_failed", user_id=user_id, ip=request.client.host if request.client else None)
        raise HTTPException(401, "Invalid 2FA code")

    audit(
        "login_2fa",
        user_id=user_id,
        username=row["username"],
        ip=request.client.host if request.client else None,
    )
    response.delete_cookie("pending_2fa", httponly=True, samesite="lax", secure=True)
    token = create_session_cookie(row["id"])
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=30 * 86400,
    )
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "smtp_recipient_address": row["smtp_recipient_address"],
        "totp_enabled": bool(row["totp_enabled"]),
        "locale": row["locale"] or "en",
    }


@router.get("/2fa/setup")
def setup_2fa(user: dict = Depends(get_current_user)):
    if user.get("totp_enabled"):
        raise HTTPException(400, "2FA already enabled")

    with db_conn() as conn:
        row = conn.execute("SELECT totp_secret FROM users WHERE id = ?", (user["id"],)).fetchone()

    secret = row["totp_secret"] if row and row["totp_secret"] else None
    if not secret:
        secret = pyotp.random_base32()
        with db_write() as conn:
            conn.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user["id"]))

    uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="Partiu")
    return {"secret": secret, "uri": uri}


@router.post("/2fa/enable")
def enable_2fa(body: TwoFAEnableRequest, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        row = conn.execute("SELECT totp_secret FROM users WHERE id = ?", (user["id"],)).fetchone()

    if not row or not row["totp_secret"]:
        raise HTTPException(400, "Run setup first")

    if not pyotp.TOTP(row["totp_secret"]).verify(body.code, valid_window=1):
        raise HTTPException(400, "Invalid code")

    with db_write() as conn:
        conn.execute("UPDATE users SET totp_enabled = 1 WHERE id = ?", (user["id"],))

    audit("2fa_enabled", user_id=user["id"])
    return {"ok": True}


@router.post("/2fa/disable")
def disable_2fa(body: TwoFADisableRequest, user: dict = Depends(get_current_user)):
    if not body.code and not body.password:
        raise HTTPException(400, "Provide a TOTP code or current password")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT totp_secret, password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()

    if not row:
        raise HTTPException(400, "User not found")

    valid = False
    if body.code and row["totp_secret"]:
        valid = pyotp.TOTP(row["totp_secret"]).verify(body.code, valid_window=1)
    if not valid and body.password:
        valid = verify_password(body.password, row["password_hash"])

    if not valid:
        raise HTTPException(400, "Invalid code or password")

    with db_write() as conn:
        conn.execute(
            "UPDATE users SET totp_enabled = 0, totp_secret = NULL WHERE id = ?", (user["id"],)
        )

    audit("2fa_disabled", user_id=user["id"])
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token:
        revoke_session_cookie(token)
    response.delete_cookie("session", httponly=True, samesite="lax", secure=True)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    if not has_any_users():
        return JSONResponse({"detail": "Setup required", "setup_required": True}, status_code=503)
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_session_cookie(token)
    if user_id is None:
        raise HTTPException(401, "Invalid or expired session")
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, smtp_recipient_address, totp_enabled, locale FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(401, "User not found")
    return {
        "id": row["id"],
        "username": row["username"],
        "is_admin": bool(row["is_admin"]),
        "smtp_recipient_address": row["smtp_recipient_address"],
        "totp_enabled": bool(row["totp_enabled"]),
        "locale": row["locale"] or "en",
    }


@router.patch("/me")
def update_me(body: UpdateMeRequest, user: dict = Depends(get_current_user)):
    if body.locale is not None and body.locale not in _VALID_LOCALES:
        raise HTTPException(422, f"Invalid locale. Valid values: {sorted(_VALID_LOCALES)}")
    if body.locale is not None:
        with db_write() as conn:
            conn.execute("UPDATE users SET locale = ? WHERE id = ?", (body.locale, user["id"]))
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT password_hash, totp_secret, totp_enabled FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
    if not row or not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if row["totp_enabled"]:
        if not body.totp_code:
            raise HTTPException(400, "2FA code required")
        totp = pyotp.TOTP(row["totp_secret"])
        if not totp.verify(body.totp_code, valid_window=1):
            raise HTTPException(400, "Invalid 2FA code")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    with db_write() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(body.new_password), user["id"]),
        )
    audit("password_changed", user_id=user["id"])
    return {"ok": True}
