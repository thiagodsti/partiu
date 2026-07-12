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
from . import notification_service, push_service
from .domain import PushSubscription
from .dto import (
    MarkedCountDTO,
    NotificationDTO,
    OkDTO,
    PreferencesDTO,
    PreferencesUpdateDTO,
    SubscribeRequestDTO,
    TestPushResultDTO,
    UnreadCountDTO,
    UnsubscribeRequestDTO,
    VapidGenerateDTO,
    VapidPublicKeyDTO,
    VapidStatusDTO,
)
from .mappers import notification_to_dto, preferences_to_dto

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/vapid-public-key", response_model=VapidPublicKeyDTO)
async def get_vapid_public_key():
    keys = push_service.get_effective_vapid_keys()
    if not keys.public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return VapidPublicKeyDTO(public_key=keys.public_key)


@router.get("/vapid/status", response_model=VapidStatusDTO)
async def vapid_status(user: dict = Depends(require_admin)):
    keys = push_service.get_effective_vapid_keys()
    return VapidStatusDTO(
        configured=bool(keys.public_key and keys.private_key),
        source=keys.source,
        public_key=keys.public_key or None,
    )


@router.post("/vapid/generate", response_model=VapidGenerateDTO)
async def generate_vapid_keys(user: dict = Depends(require_admin)):
    """Generate a new VAPID key pair and store it in global_settings."""
    try:
        keys = push_service.generate_and_store_vapid_keys()
    except ImportError:
        raise HTTPException(status_code=500, detail="pywebpush not installed")

    return VapidGenerateDTO(ok=True, public_key=keys.public_key, source=keys.source)


@router.post("/subscribe", response_model=OkDTO)
async def subscribe(
    body: SubscribeRequestDTO,
    request: Request,
    user: dict = Depends(get_current_user),
):
    subscription = PushSubscription(
        endpoint=body.subscription.endpoint,
        p256dh=body.subscription.keys.p256dh,
        auth=body.subscription.keys.auth,
    )
    user_agent = request.headers.get("user-agent", "")
    push_service.subscribe(user["id"], subscription, user_agent)
    return OkDTO(ok=True)


@router.delete("/subscribe", response_model=OkDTO)
async def unsubscribe(
    body: UnsubscribeRequestDTO,
    user: dict = Depends(get_current_user),
):
    push_service.unsubscribe(user["id"], body.endpoint)
    return OkDTO(ok=True)


@router.get("/preferences", response_model=PreferencesDTO)
async def get_preferences(user: dict = Depends(get_current_user)):
    return preferences_to_dto(push_service.preferences_from_user(user))


@router.post("/preferences")
async def update_preferences(
    body: PreferencesUpdateDTO,
    user: dict = Depends(get_current_user),
):
    updates = body.model_dump(exclude_none=True)
    try:
        applied = push_service.update_preferences(user["id"], updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True, **applied}


@router.post("/badge/clear", response_model=OkDTO)
async def clear_badge(user: dict = Depends(get_current_user)):
    """Reset the unread notification badge counter for this user."""
    push_service.clear_unread(user["id"])
    return OkDTO(ok=True)


# ---------------------------------------------------------------------------
# In-app notification inbox
# ---------------------------------------------------------------------------


@router.get("/inbox", response_model=list[NotificationDTO])
async def inbox(user: dict = Depends(get_current_user)):
    """List the user's in-app notifications, newest first."""
    notifications = notification_service.list_notifications(user["id"])
    return [notification_to_dto(n) for n in notifications]


@router.get("/inbox/count", response_model=UnreadCountDTO)
async def inbox_count(user: dict = Depends(get_current_user)):
    """Return the count of unread in-app notifications."""
    return UnreadCountDTO(unread=notification_service.get_unread_count(user["id"]))


@router.post("/inbox/read-all", response_model=MarkedCountDTO)
async def read_all(user: dict = Depends(get_current_user)):
    """Mark all in-app notifications as read."""
    count = notification_service.mark_all_read(user["id"])
    return MarkedCountDTO(ok=True, marked=count)


@router.post("/inbox/{notification_id}/read", response_model=OkDTO)
async def read_one(notification_id: int, user: dict = Depends(get_current_user)):
    """Mark a single in-app notification as read."""
    if not notification_service.mark_read(notification_id, user["id"]):
        raise HTTPException(status_code=404, detail="Notification not found")
    return OkDTO(ok=True)


@router.delete("/inbox/{notification_id}", status_code=204)
async def delete_one(notification_id: int, user: dict = Depends(get_current_user)):
    """Delete a single in-app notification."""
    if not notification_service.delete_notification(notification_id, user["id"]):
        raise HTTPException(status_code=404, detail="Notification not found")


@router.post("/test", response_model=TestPushResultDTO)
@limiter.limit("5/minute")
async def test_push(request: Request, user: dict = Depends(get_current_user)):
    keys = push_service.get_effective_vapid_keys()
    if not keys.public_key or not keys.private_key:
        raise HTTPException(
            status_code=503, detail="Push notifications not configured on this server"
        )

    from ..utils.i18n import t as i18n_t

    subs = push_service.get_subscriptions(user["id"])
    if not subs:
        raise HTTPException(
            status_code=400,
            detail="No push subscriptions found for your account. Enable notifications in your browser first.",
        )

    locale = user.get("locale") or "en"
    sent = push_service.send_push(
        user["id"],
        {
            "title": i18n_t("notif.test_title", locale),
            "body": i18n_t("notif.test_body", locale),
            "url": "/#/",
        },
    )
    return TestPushResultDTO(ok=sent > 0, sent=sent)
