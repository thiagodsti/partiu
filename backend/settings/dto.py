"""Request/response DTOs for the settings HTTP API (routes.py)."""

from pydantic import BaseModel


class SettingsDTO(BaseModel):
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
    smtp_server_port: int | None = None


class SettingsUpdateDTO(BaseModel):
    # Per-user settings
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    smtp_recipient_address: str | None = None
    smtp_allowed_senders: str | None = None
    # Immich integration
    immich_url: str | None = None
    immich_api_key: str | None = None
    # Expense preferences
    default_currency: str | None = None
    # Global settings (admin only)
    sync_interval_minutes: int | None = None
    first_sync_days: int | None = None
    smtp_server_enabled: bool | None = None
    smtp_server_port: int | None = None
    smtp_domain: str | None = None


class TestImapRequestDTO(BaseModel):
    imap_host: str | None = None
    imap_port: int | None = None
    gmail_address: str | None = None
    gmail_app_password: str | None = None


class OkMessageDTO(BaseModel):
    ok: bool
    message: str


class AirportCountDTO(BaseModel):
    count: int
    # How many of them carry the size/scheduled-service ranking that airport-name
    # resolution needs. Short of `count` means names resolve without it.
    ranked: int = 0


class AirportReloadDTO(BaseModel):
    ok: bool
    count: int


class NonFlightDomainDTO(BaseModel):
    domain: str
    note: str
    created_at: str


class AddDomainRequestDTO(BaseModel):
    domain: str
    note: str = ""


class AddDomainResponseDTO(BaseModel):
    ok: bool
    domain: str


class OkDTO(BaseModel):
    ok: bool


class IntegrationStatusDTO(BaseModel):
    """One optional integration's configuration state.

    Deliberately carries no key material — only whether something is set and
    which environment variable sets it.
    """

    key: str
    configured: bool
    state: str
    env_var: str | None
