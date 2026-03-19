"""
Web Push (VAPID) helpers.

Low-level functions for:
  - storing/removing push subscriptions per device
  - sending a push notification to all subscriptions of a user
  - logging sent notifications to prevent duplicates
"""

import json
import logging
from datetime import UTC, datetime
from typing import TypedDict

logger = logging.getLogger(__name__)


class _VapidKeys(TypedDict):
    private_key: str
    public_key: str
    subject: str
    source: str  # 'env' | 'database' | 'none'


def ensure_vapid_keys() -> None:
    """Auto-generate and store VAPID keys on first run if none are configured."""
    from .config import settings

    # Env vars take priority — nothing to do
    if settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY:
        return

    from .database import get_global_setting

    if get_global_setting("vapid_private_key") and get_global_setting("vapid_public_key"):
        return  # Already in DB

    try:
        import base64

        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )
        from pywebpush import Vapid

        v = Vapid()
        v.generate_keys()
        priv_der = v.private_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
        pub_raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        private_key = base64.urlsafe_b64encode(priv_der).decode().rstrip("=")
        public_key = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")

        from .database import set_global_setting

        set_global_setting("vapid_private_key", private_key)
        set_global_setting("vapid_public_key", public_key)
        logger.info("VAPID keys auto-generated and stored in database")
    except Exception:
        logger.exception(
            "Failed to auto-generate VAPID keys — push notifications will be unavailable"
        )


def get_effective_vapid_keys() -> _VapidKeys:
    """Return VAPID keys: env vars take priority, then global_settings DB values."""
    from .config import settings

    if settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY:
        return {
            "private_key": settings.VAPID_PRIVATE_KEY,
            "public_key": settings.VAPID_PUBLIC_KEY,
            "subject": settings.VAPID_SUBJECT,
            "source": "env",
        }

    from .database import get_global_setting

    private = get_global_setting("vapid_private_key")
    public = get_global_setting("vapid_public_key")
    subject = (
        get_global_setting("vapid_subject") or settings.VAPID_SUBJECT or "mailto:admin@example.com"
    )

    return {
        "private_key": private,
        "public_key": public,
        "subject": subject,
        "source": "database" if (private and public) else "none",
    }


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------


def save_subscription(user_id: int, subscription: dict, user_agent: str = "") -> None:
    """Upsert a push subscription for a user/device pair."""
    from .database import db_write

    endpoint = subscription.get("endpoint", "")
    keys = subscription.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    with db_write() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, endpoint) DO UPDATE SET
                 p256dh = excluded.p256dh,
                 auth = excluded.auth,
                 user_agent = excluded.user_agent""",
            (user_id, endpoint, p256dh, auth, user_agent),
        )


def delete_subscription(user_id: int, endpoint: str) -> None:
    """Remove a specific push subscription."""
    from .database import db_write

    with db_write() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user_id, endpoint),
        )


def get_subscriptions(user_id: int) -> list[dict]:
    """Return all active push subscriptions for a user."""
    from .database import db_conn

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


def send_push(user_id: int, payload: dict) -> int:
    """
    Send a push notification to all subscriptions of a user.

    payload should be: {"title": "...", "body": "...", "url": "..."}

    Returns the number of successful sends.
    """
    keys = get_effective_vapid_keys()
    if not keys["private_key"] or not keys["public_key"]:
        logger.debug("VAPID keys not configured — skipping push for user %d", user_id)
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed — skipping push notification")
        return 0

    subs = get_subscriptions(user_id)
    if not subs:
        return 0

    data = json.dumps(payload)
    sent = 0
    dead = []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=data,
                vapid_private_key=keys["private_key"],
                vapid_claims={
                    "sub": keys["subject"],
                },
            )
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                # Endpoint is gone — remove it
                dead.append(sub["endpoint"])
                logger.debug("Push endpoint gone (HTTP %s), removing", status)
            else:
                logger.warning("Push send failed for user %d: %s", user_id, e)
        except Exception as e:  # noqa: BLE001
            logger.warning("Unexpected push error for user %d: %s", user_id, e)

    for endpoint in dead:
        delete_subscription(user_id, endpoint)

    return sent


# ---------------------------------------------------------------------------
# Deduplication log
# ---------------------------------------------------------------------------


def already_sent(user_id: int, flight_id: str, notif_type: str) -> bool:
    """Return True if this notification was already sent."""
    from .database import db_conn

    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM notification_log WHERE user_id = ? AND flight_id = ? AND notif_type = ?",
            (user_id, flight_id, notif_type),
        ).fetchone()
    return row is not None


def log_sent(user_id: int, flight_id: str, notif_type: str) -> None:
    """Record that a notification was sent (INSERT OR IGNORE for idempotency)."""
    from .database import db_write

    with db_write() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notification_log (user_id, flight_id, notif_type, sent_at) VALUES (?, ?, ?, ?)",
            (user_id, flight_id, notif_type, datetime.now(UTC).isoformat()),
        )
