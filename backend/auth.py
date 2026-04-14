"""
Authentication helpers: password hashing, session cookies, FastAPI dependencies.
"""

import os
import secrets

import bcrypt
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))
_serializer = None


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        from .config import settings

        key = settings.SECRET_KEY
        if not key:
            raise RuntimeError(
                "SECRET_KEY is not set. Generate one with:\n"
                '  python -c "import secrets; print(secrets.token_hex(32))"\n'
                "and add SECRET_KEY=<value> to your .env file."
            )
        _serializer = URLSafeTimedSerializer(key, salt="session")
    return _serializer


def validate_secret_key() -> None:
    """Call at startup to fail loudly if SECRET_KEY is missing."""
    _get_serializer()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_session_cookie(user_id: int) -> str:
    from datetime import UTC, datetime, timedelta

    from .config import settings
    from .database import db_write

    sid = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.SESSION_MAX_AGE_DAYS)
    with db_write() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (sid, user_id, now.isoformat(), expires.isoformat()),
        )
    return _get_serializer().dumps({"uid": user_id, "sid": sid})


def _decode_session_token_raw(token: str) -> dict | None:
    """Decode a session token without checking revocation — use only for logout."""
    try:
        from .config import settings

        max_age = settings.SESSION_MAX_AGE_DAYS * 86400
        return _get_serializer().loads(token, max_age=max_age)
    except Exception:
        return None


def decode_session_cookie(token: str) -> int | None:
    try:
        from .config import settings
        from .database import db_conn

        max_age = settings.SESSION_MAX_AGE_DAYS * 86400
        data = _get_serializer().loads(token, max_age=max_age)
        uid = data.get("uid")
        sid = data.get("sid")
        if not uid or not sid:
            return None
        with db_conn() as conn:
            row = conn.execute("SELECT revoked FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None or row["revoked"]:
            return None
        return uid
    except (BadSignature, SignatureExpired, Exception):
        return None


def revoke_session_cookie(token: str) -> None:
    """Mark the session identified by token as revoked in the DB."""
    data = _decode_session_token_raw(token)
    if data and data.get("sid"):
        try:
            from .database import db_write

            with db_write() as conn:
                conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (data["sid"],))
        except Exception:
            pass


def create_pending_2fa_cookie(user_id: int) -> str:
    s = URLSafeTimedSerializer(_get_serializer().secret_key, salt="pending_2fa")
    return s.dumps({"uid": user_id})


def decode_pending_2fa_cookie(token: str) -> int | None:
    try:
        s = URLSafeTimedSerializer(_get_serializer().secret_key, salt="pending_2fa")
        data = s.loads(token, max_age=300)  # 5 minutes
        return data.get("uid")
    except Exception:
        return None


def has_any_users() -> bool:
    from .database import db_conn

    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] > 0


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = decode_session_cookie(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    from .database import db_conn

    with db_conn() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, smtp_recipient_address, smtp_allowed_senders, gmail_address, gmail_app_password, imap_host, imap_port, totp_enabled, sync_interval_minutes, immich_url, immich_api_key, notif_flight_reminder, notif_checkin_reminder, notif_trip_reminder, notif_delay_alert, notif_boarding_pass, notif_new_flight FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    user = dict(row)
    from .crypto import decrypt

    for field in ("gmail_app_password", "immich_api_key"):
        if user.get(field):
            user[field] = decrypt(user[field])
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def revoke_all_user_sessions(user_id: int) -> None:
    """Revoke all active sessions for a user (call on password change, 2FA change, etc.)."""
    from .database import db_write

    with db_write() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))


def get_user_imap_settings(user: dict) -> dict:
    """Return per-user IMAP settings, falling back to Gmail defaults."""
    return {
        "gmail_address": user.get("gmail_address") or None,
        "gmail_app_password": user.get("gmail_app_password") or None,
        "imap_host": user.get("imap_host") or "imap.gmail.com",
        "imap_port": user.get("imap_port") or 993,
    }
