"""
Notifications API routes.

  GET    /api/notifications/vapid-public-key  — return VAPID public key
  GET    /api/notifications/vapid/status      — admin: VAPID config status
  POST   /api/notifications/vapid/generate    — admin: generate & store VAPID keys
  POST   /api/notifications/subscribe         — save a push subscription
  DELETE /api/notifications/subscribe         — remove a push subscription
  GET    /api/notifications/preferences       — get per-user notification prefs
  POST   /api/notifications/preferences       — update prefs
  POST   /api/notifications/test              — send a test push
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user, require_admin
from ..limiter import limiter
from ..push import get_effective_vapid_keys

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    keys = get_effective_vapid_keys()
    if not keys["public_key"]:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": keys["public_key"]}


@router.get("/vapid/status")
async def vapid_status(user: dict = Depends(require_admin)):
    keys = get_effective_vapid_keys()
    return {
        "configured": bool(keys["public_key"] and keys["private_key"]),
        "source": keys["source"],
        "public_key": keys["public_key"] or None,
    }


@router.post("/vapid/generate")
async def generate_vapid_keys(user: dict = Depends(require_admin)):
    """Generate a new VAPID key pair and store it in global_settings."""
    try:
        from pywebpush import Vapid
    except ImportError:
        raise HTTPException(status_code=500, detail="pywebpush not installed")

    import base64

    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    v = Vapid()
    v.generate_keys()

    # Serialize to URL-safe base64 (no padding) — format webpush expects
    priv_der = v.private_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    pub_raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    private_key = base64.urlsafe_b64encode(priv_der).decode().rstrip("=")
    public_key = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")

    from ..database import set_global_setting

    set_global_setting("vapid_private_key", private_key)
    set_global_setting("vapid_public_key", public_key)

    return {
        "ok": True,
        "public_key": public_key,
        "source": "database",
    }


@router.post("/subscribe")
async def subscribe(
    request: Request,
    user: dict = Depends(get_current_user),
):
    body = await request.json()
    subscription = body.get("subscription")
    if not subscription or not subscription.get("endpoint"):
        raise HTTPException(status_code=422, detail="Missing subscription data")

    user_agent = request.headers.get("user-agent", "")
    from ..push import save_subscription

    save_subscription(user["id"], subscription, user_agent)
    return {"ok": True}


@router.delete("/subscribe")
async def unsubscribe(
    request: Request,
    user: dict = Depends(get_current_user),
):
    body = await request.json()
    endpoint = body.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=422, detail="Missing endpoint")

    from ..push import delete_subscription

    delete_subscription(user["id"], endpoint)
    return {"ok": True}


@router.get("/preferences")
async def get_preferences(user: dict = Depends(get_current_user)):
    return {
        "flight_reminder": bool(user.get("notif_flight_reminder", 1)),
        "checkin_reminder": bool(user.get("notif_checkin_reminder", 1)),
        "trip_reminder": bool(user.get("notif_trip_reminder", 1)),
        "delay_alert": bool(user.get("notif_delay_alert", 1)),
        "boarding_pass": bool(user.get("notif_boarding_pass", 1)),
        "new_flight": bool(user.get("notif_new_flight", 1)),
        "failed_parse": bool(user.get("notif_failed_parse", 1)),
    }


@router.post("/preferences")
async def update_preferences(
    request: Request,
    user: dict = Depends(get_current_user),
):
    body = await request.json()
    allowed = {
        "flight_reminder",
        "checkin_reminder",
        "trip_reminder",
        "delay_alert",
        "boarding_pass",
        "new_flight",
        "failed_parse",
    }
    updates = {k: int(bool(v)) for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=422, detail="No valid preference fields")

    from ..database import db_write

    # Fixed column map — avoids dynamic SQL construction entirely
    col_map = {
        "flight_reminder": "notif_flight_reminder",
        "checkin_reminder": "notif_checkin_reminder",
        "trip_reminder": "notif_trip_reminder",
        "delay_alert": "notif_delay_alert",
        "boarding_pass": "notif_boarding_pass",
        "new_flight": "notif_new_flight",
        "failed_parse": "notif_failed_parse",
    }
    with db_write() as conn:
        for key, val in updates.items():
            col = col_map[key]
            conn.execute(f"UPDATE users SET {col} = ? WHERE id = ?", (val, user["id"]))

    return {"ok": True, **{k: bool(v) for k, v in updates.items()}}


@router.post("/badge/clear")
async def clear_badge(user: dict = Depends(get_current_user)):
    """Reset the unread notification badge counter for this user."""
    from ..push import clear_unread

    clear_unread(user["id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# In-app notification inbox
# ---------------------------------------------------------------------------


@router.get("/inbox")
async def inbox(user: dict = Depends(get_current_user)):
    """List the user's in-app notifications, newest first."""
    from ..notifications_store import list_notifications

    return list_notifications(user["id"])


@router.get("/inbox/count")
async def inbox_count(user: dict = Depends(get_current_user)):
    """Return the count of unread in-app notifications."""
    from ..notifications_store import get_unread_count

    return {"unread": get_unread_count(user["id"])}


@router.post("/inbox/read-all")
async def read_all(user: dict = Depends(get_current_user)):
    """Mark all in-app notifications as read."""
    from ..notifications_store import mark_all_read

    count = mark_all_read(user["id"])
    return {"ok": True, "marked": count}


@router.post("/inbox/{notification_id}/read")
async def read_one(notification_id: int, user: dict = Depends(get_current_user)):
    """Mark a single in-app notification as read."""
    from ..notifications_store import mark_read

    if not mark_read(notification_id, user["id"]):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.delete("/inbox/{notification_id}", status_code=204)
async def delete_one(notification_id: int, user: dict = Depends(get_current_user)):
    """Delete a single in-app notification."""
    from ..notifications_store import delete_notification

    if not delete_notification(notification_id, user["id"]):
        raise HTTPException(status_code=404, detail="Notification not found")


@router.post("/test")
@limiter.limit("5/minute")
async def test_push(request: Request, user: dict = Depends(get_current_user)):
    keys = get_effective_vapid_keys()
    if not keys["public_key"] or not keys["private_key"]:
        raise HTTPException(
            status_code=503, detail="Push notifications not configured on this server"
        )

    from ..push import get_subscriptions, send_push

    subs = get_subscriptions(user["id"])
    if not subs:
        raise HTTPException(
            status_code=400,
            detail="No push subscriptions found for your account. Enable notifications in your browser first.",
        )

    sent = send_push(
        user["id"],
        {
            "title": "Partiu — test notification",
            "body": "Push notifications are working!",
            "url": "/#/",
        },
    )
    return {"ok": sent > 0, "sent": sent}
