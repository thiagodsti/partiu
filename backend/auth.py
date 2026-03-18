"""
Authentication helpers: password hashing, session cookies, FastAPI dependencies.
"""
import os
import secrets
import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, Depends

_serializer = None


def _get_serializer():
    global _serializer
    if _serializer is None:
        from .config import settings
        key = settings.SECRET_KEY
        if not key:
            key = _ensure_secret_key()
        _serializer = URLSafeTimedSerializer(key, salt="session")
    return _serializer


def _ensure_secret_key() -> str:
    """Generate and persist a SECRET_KEY to .env if missing."""
    key = secrets.token_hex(32)
    env_path = ".env"
    try:
        lines = []
        if os.path.exists(env_path):
            with open(env_path) as f:
                lines = f.readlines()
        # Replace or append SECRET_KEY
        found = False
        for i, line in enumerate(lines):
            if line.startswith("SECRET_KEY="):
                lines[i] = f"SECRET_KEY={key}\n"
                found = True
                break
        if not found:
            lines.append(f"\nSECRET_KEY={key}\n")
        with open(env_path, "w") as f:
            f.writelines(lines)
    except Exception:
        pass  # Non-fatal; key will be regenerated next restart
    return key


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_session_cookie(user_id: int) -> str:
    return _get_serializer().dumps({"uid": user_id})


def decode_session_cookie(token: str) -> int | None:
    try:
        from .config import settings
        max_age = settings.SESSION_MAX_AGE_DAYS * 86400
        data = _get_serializer().loads(token, max_age=max_age)
        return data.get("uid")
    except (BadSignature, SignatureExpired, Exception):
        return None


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
            "SELECT id, username, is_admin, smtp_recipient_address, gmail_address, gmail_app_password, imap_host, imap_port, totp_enabled FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(row)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_user_imap_settings(user: dict) -> dict:
    """Return per-user IMAP settings. No global fallback — each user configures their own."""
    from .config import settings
    return {
        "gmail_address": user.get("gmail_address") or None,
        "gmail_app_password": user.get("gmail_app_password") or None,
        "imap_host": user.get("imap_host") or settings.IMAP_HOST,
        "imap_port": user.get("imap_port") or settings.IMAP_PORT,
    }
