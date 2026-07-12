"""Use cases for app settings: per-user config, admin-only global config, IMAP/Immich
connectivity tests, airport count/reload, and non-flight-domain admin management."""

import imaplib

from ..validation import validate_external_host, validate_external_url
from .domain import NonFlightDomain, UserSettings
from .errors import AdminRequiredError, SmtpConflictError, ValidationError
from .repository import SettingsRepository

_GLOBAL_FIELD_COLUMNS = {
    "sync_interval_minutes",
    "first_sync_days",
    "smtp_server_enabled",
    "smtp_server_port",
    "smtp_domain",
}


class SettingsService:
    def __init__(self, repository: SettingsRepository | None = None):
        self._repository = repository or SettingsRepository()

    def get_settings(self, user: dict) -> UserSettings:
        """Per-user fields come straight from the already-loaded ``user`` dict
        (get_current_user already selects them) — only global config needs a lookup."""
        settings = UserSettings(
            gmail_address=user.get("gmail_address") or "",
            gmail_app_password_set=bool(user.get("gmail_app_password")),
            imap_host=user.get("imap_host") or "imap.gmail.com",
            imap_port=user.get("imap_port") or 993,
            sync_interval_minutes=int(
                self._repository.get_global_setting("sync_interval_minutes", "10")
            ),
            first_sync_days=int(self._repository.get_global_setting("first_sync_days", "90")),
            smtp_server_enabled=self._repository.get_global_setting("smtp_server_enabled", "false")
            == "true",
            smtp_domain=self._repository.get_global_setting("smtp_domain", ""),
            smtp_recipient_address=user.get("smtp_recipient_address") or "",
            smtp_allowed_senders=user.get("smtp_allowed_senders") or "",
            immich_url=user.get("immich_url") or "",
            immich_api_key_set=bool(user.get("immich_api_key")),
            default_currency=user.get("default_currency") or "EUR",
            smtp_server_port=None,
        )
        if user.get("is_admin"):
            settings.smtp_server_port = int(
                self._repository.get_global_setting("smtp_server_port", "2525")
            )
        return settings

    def update_settings(self, user: dict, updates: dict) -> None:
        """``updates`` is the request body with unset fields already excluded
        (routes.py calls ``body.model_dump(exclude_none=True)``)."""
        from ..crypto import encrypt

        user_updates: dict = {}

        if "gmail_address" in updates:
            user_updates["gmail_address"] = updates["gmail_address"]
        if "gmail_app_password" in updates:
            user_updates["gmail_app_password"] = encrypt(updates["gmail_app_password"])
        if "imap_host" in updates:
            self._validate_imap_host(updates["imap_host"])
            user_updates["imap_host"] = updates["imap_host"].strip()
        if "imap_port" in updates:
            port = updates["imap_port"]
            if not 1 <= port <= 65535:
                raise ValidationError("IMAP port must be between 1 and 65535")
            user_updates["imap_port"] = port
        if "smtp_recipient_address" in updates:
            recipient = updates["smtp_recipient_address"].strip()
            if not recipient:
                smtp_domain = self._repository.get_global_setting("smtp_domain", "")
                if smtp_domain:
                    recipient = f"{user['username']}@{smtp_domain}"
            if recipient and self._repository.has_smtp_conflict(recipient, user["id"]):
                raise SmtpConflictError(f'"{recipient}" is already in use by another user')
            user_updates["smtp_recipient_address"] = recipient
        if "smtp_allowed_senders" in updates:
            user_updates["smtp_allowed_senders"] = updates["smtp_allowed_senders"]
        if "immich_url" in updates:
            user_updates["immich_url"] = self._validate_external_url(
                updates["immich_url"], "Immich URL"
            )
        if "immich_api_key" in updates:
            user_updates["immich_api_key"] = encrypt(updates["immich_api_key"])
        if "default_currency" in updates:
            from ..expenses import SUPPORTED_CURRENCIES

            currency = updates["default_currency"].upper()
            if currency not in SUPPORTED_CURRENCIES:
                raise ValidationError(f"Unsupported currency: {updates['default_currency']}")
            user_updates["default_currency"] = currency

        if user_updates:
            self._repository.update_user_settings(user["id"], user_updates)

        # Global settings — require admin
        has_global = any(key in updates for key in _GLOBAL_FIELD_COLUMNS)
        if has_global:
            if not user.get("is_admin"):
                raise AdminRequiredError("Admin access required for global settings")
            if "sync_interval_minutes" in updates:
                value = updates["sync_interval_minutes"]
                if not 1 <= value <= 1440:
                    raise ValidationError("sync_interval_minutes must be between 1 and 1440")
                self._repository.set_global_setting("sync_interval_minutes", str(value))
            if "first_sync_days" in updates:
                value = updates["first_sync_days"]
                if not 1 <= value <= 3650:
                    raise ValidationError("first_sync_days must be between 1 and 3650")
                self._repository.set_global_setting("first_sync_days", str(value))
            if "smtp_server_enabled" in updates:
                self._repository.set_global_setting(
                    "smtp_server_enabled", "true" if updates["smtp_server_enabled"] else "false"
                )
            if "smtp_server_port" in updates:
                self._repository.set_global_setting(
                    "smtp_server_port", str(updates["smtp_server_port"])
                )
            if "smtp_domain" in updates:
                self._repository.set_global_setting("smtp_domain", updates["smtp_domain"])

    def test_imap(
        self,
        user: dict,
        host: str | None,
        port: int | None,
        address: str | None,
        password: str | None,
    ) -> str:
        """Try connecting and authenticating to the IMAP server with the given (or
        stored) credentials. Returns a success message; raises ValidationError."""
        effective_host = (host or user.get("imap_host") or "imap.gmail.com").strip()
        effective_port = port or user.get("imap_port") or 993
        effective_address = address or user.get("gmail_address") or ""
        effective_password = password or user.get("gmail_app_password") or ""

        if not effective_address:
            raise ValidationError("Email address is required")
        if not effective_password:
            raise ValidationError(
                "Password is required — save your settings first or enter it above"
            )

        self._validate_imap_host(effective_host)

        try:
            imap = imaplib.IMAP4_SSL(effective_host, effective_port, timeout=10)
            imap.login(effective_address, effective_password)
            imap.logout()
        except imaplib.IMAP4.error as e:
            raise ValidationError(f"Authentication failed: {e}") from e
        except OSError as e:
            raise ValidationError(
                f"Could not connect to {effective_host}:{effective_port} — {e}"
            ) from e
        except Exception as e:
            raise ValidationError(f"Connection error: {e}") from e

        return f"Connected to {effective_host}:{effective_port} successfully"

    async def test_immich(self, user: dict) -> str:
        """Test the configured Immich connection. Returns a success message."""
        from ..crypto import decrypt
        from ..integrations.immich.client import test_connection

        immich_url = (user.get("immich_url") or "").strip()
        immich_api_key = decrypt((user.get("immich_api_key") or "").strip())
        if not immich_url:
            raise ValidationError("Immich URL is not configured")
        if not immich_api_key:
            raise ValidationError("Immich API key is not configured")

        try:
            result = await test_connection(immich_url, immich_api_key)
        except ValueError as e:
            raise ValidationError(str(e)) from e

        version = result.get("version", "unknown")
        return (
            f"Connected to Immich {version}"
            if version != "unknown"
            else "Connected to Immich successfully"
        )

    def get_airport_count(self) -> int:
        return self._repository.get_airport_count()

    def reload_airports(self) -> int:
        return self._repository.reload_airports()

    def list_non_flight_domains(self) -> list[NonFlightDomain]:
        return [NonFlightDomain(**d) for d in self._repository.list_non_flight_domains()]

    def add_non_flight_domain(self, domain: str, note: str) -> str:
        domain = domain.strip().lower()
        if domain:
            self._repository.add_non_flight_domain(domain, note)
        return domain

    def remove_non_flight_domain(self, domain: str) -> None:
        self._repository.remove_non_flight_domain(domain)

    @staticmethod
    def _validate_imap_host(host: str) -> None:
        """Reject private/loopback addresses to prevent SSRF."""
        try:
            validate_external_host(host, "IMAP host")
        except ValueError as e:
            raise ValidationError(str(e)) from e

    @staticmethod
    def _validate_external_url(url: str, field_name: str = "URL") -> str:
        """Validate a user-supplied HTTP/HTTPS URL and reject private/loopback targets (SSRF prevention)."""
        try:
            return validate_external_url(url, field_name)
        except ValueError as e:
            raise ValidationError(str(e)) from e


settings_service = SettingsService()
