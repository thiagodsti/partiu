"""Web Push (VAPID) use cases: key management, sending, subscriptions, preferences."""

import base64
import json
import logging

from .domain import NotificationPreferences, PushSubscription, VapidKeys
from .mappers import user_to_preferences
from .push_repository import PREFERENCE_COLUMNS, PushRepository

logger = logging.getLogger(__name__)


class PushService:
    def __init__(self, repository: PushRepository | None = None):
        self._repository = repository or PushRepository()

    # -- VAPID key management ---------------------------------------------

    def ensure_vapid_keys(self) -> None:
        """Auto-generate and store VAPID keys on first run if none are configured."""
        from ..config import settings

        # Env vars take priority — nothing to do
        if settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY:
            return

        existing_private, existing_public, _ = self._repository.get_vapid_settings()
        if existing_private and existing_public:
            return  # Already in DB

        try:
            private_key, public_key = self._generate_vapid_keypair()
            self._repository.save_vapid_keys(private_key, public_key)
            logger.info("VAPID keys auto-generated and stored in database")
        except Exception:
            logger.exception(
                "Failed to auto-generate VAPID keys — push notifications will be unavailable"
            )

    def get_effective_vapid_keys(self) -> VapidKeys:
        """Return VAPID keys: env vars take priority, then database values."""
        from ..config import settings

        if settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY:
            return VapidKeys(
                private_key=settings.VAPID_PRIVATE_KEY,
                public_key=settings.VAPID_PUBLIC_KEY,
                subject=settings.VAPID_SUBJECT,
                source="env",
            )

        private, public, subject = self._repository.get_vapid_settings()
        subject = subject or settings.VAPID_SUBJECT or "mailto:admin@example.com"
        return VapidKeys(
            private_key=private,
            public_key=public,
            subject=subject,
            source="database" if (private and public) else "none",
        )

    def generate_and_store_vapid_keys(self) -> VapidKeys:
        """Force-generate a new VAPID key pair (admin action) and persist it.

        Raises ImportError if pywebpush is not installed.
        """
        private_key, public_key = self._generate_vapid_keypair()
        self._repository.save_vapid_keys(private_key, public_key)
        return VapidKeys(
            private_key=private_key, public_key=public_key, subject="", source="database"
        )

    @staticmethod
    def _generate_vapid_keypair() -> tuple[str, str]:
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
        return private_key, public_key

    # -- Subscriptions -------------------------------------------------------

    def subscribe(self, user_id: int, subscription: PushSubscription, user_agent: str = "") -> None:
        self._repository.save_subscription(user_id, subscription, user_agent)

    def unsubscribe(self, user_id: int, endpoint: str) -> None:
        self._repository.delete_subscription(user_id, endpoint)

    def get_subscriptions(self, user_id: int) -> list[PushSubscription]:
        return self._repository.get_subscriptions(user_id)

    # -- Badge counter ---------------------------------------------------------

    def get_unread_count(self, user_id: int) -> int:
        return self._repository.get_unread_count(user_id)

    def clear_unread(self, user_id: int) -> None:
        self._repository.clear_unread(user_id)

    # -- Send ---------------------------------------------------------------

    def send_push(self, user_id: int, payload: dict) -> int:
        """
        Send a push notification to all subscriptions of a user.

        payload should be: {"title": "...", "body": "...", "url": "..."}

        Returns the number of successful sends.
        """
        keys = self.get_effective_vapid_keys()
        if not keys.private_key or not keys.public_key:
            logger.debug("VAPID keys not configured — skipping push for user %d", user_id)
            return 0

        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            logger.warning("pywebpush not installed — skipping push notification")
            return 0

        subs = self._repository.get_subscriptions(user_id)
        if not subs:
            return 0

        # Include badge count (+1 for this notification) so the service worker can set the app badge
        try:
            badge = self._repository.get_unread_count(user_id) + 1
        except Exception:
            badge = 1
        data = json.dumps({**payload, "badge": badge})
        sent = 0
        dead = []

        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=data,
                    vapid_private_key=keys.private_key,
                    vapid_claims={
                        "sub": keys.subject,
                    },
                )
                sent += 1
            except WebPushException as e:
                status = e.response.status_code if e.response is not None else None
                if status in (404, 410):
                    # Endpoint is gone — remove it
                    dead.append(sub.endpoint)
                    logger.debug("Push endpoint gone (HTTP %s), removing", status)
                else:
                    logger.warning("Push send failed for user %d: %s", user_id, e)
            except Exception as e:  # noqa: BLE001
                logger.warning("Unexpected push error for user %d: %s", user_id, e)

        for endpoint in dead:
            self._repository.delete_subscription(user_id, endpoint)

        if sent > 0:
            try:
                self._repository.increment_unread(user_id)
            except Exception:
                pass

        return sent

    # -- Deduplication log ---------------------------------------------------

    def already_sent(self, user_id: int, flight_id: str, notif_type: str) -> bool:
        return self._repository.already_sent(user_id, flight_id, notif_type)

    def log_sent(self, user_id: int, flight_id: str, notif_type: str) -> None:
        self._repository.log_sent(user_id, flight_id, notif_type)

    # -- Preferences ---------------------------------------------------------

    def preferences_from_user(self, user: dict) -> NotificationPreferences:
        return user_to_preferences(user)

    def is_preference_enabled(self, user_id: int, pref_key: str) -> bool:
        return self._repository.is_enabled(user_id, pref_key)

    def get_locale(self, user_id: int) -> str:
        return self._repository.get_locale(user_id)

    def update_preferences(self, user_id: int, updates: dict) -> dict[str, bool]:
        """Update the given preference fields.

        ``updates`` may contain arbitrary keys; only ones matching a known preference
        column are applied. Raises ValueError if none of the keys are valid.
        """
        valid = {k: bool(v) for k, v in updates.items() if k in PREFERENCE_COLUMNS}
        if not valid:
            raise ValueError("No valid preference fields")
        self._repository.update_preferences(user_id, valid)
        return valid


push_service = PushService()
