"""Domain objects for the app-settings feature (per-user + admin-only global config)."""

from dataclasses import dataclass


@dataclass
class UserSettings:
    gmail_address: str
    gmail_app_password_set: bool
    imap_host: str
    imap_port: int
    sync_interval_minutes: int
    first_sync_days: int
    smtp_server_enabled: bool
    smtp_domain: str
    smtp_recipient_address: str
    smtp_allowed_senders: str
    immich_url: str
    immich_api_key_set: bool
    default_currency: str
    smtp_server_port: int | None  # admin only; None for non-admins


@dataclass
class NonFlightDomain:
    domain: str
    note: str
    created_at: str
