"""Conversions between domain objects and DTOs (settings has no SQL rows of its own
worth wrapping — see repository.py for why)."""

from .domain import NonFlightDomain, UserSettings
from .dto import NonFlightDomainDTO, SettingsDTO


def settings_to_dto(settings: UserSettings) -> SettingsDTO:
    return SettingsDTO(
        gmail_address=settings.gmail_address,
        gmail_app_password_set=settings.gmail_app_password_set,
        imap_host=settings.imap_host,
        imap_port=settings.imap_port,
        sync_interval_minutes=settings.sync_interval_minutes,
        first_sync_days=settings.first_sync_days,
        smtp_server_enabled=settings.smtp_server_enabled,
        smtp_domain=settings.smtp_domain,
        smtp_recipient_address=settings.smtp_recipient_address,
        smtp_allowed_senders=settings.smtp_allowed_senders,
        immich_url=settings.immich_url,
        immich_api_key_set=settings.immich_api_key_set,
        default_currency=settings.default_currency,
        smtp_server_port=settings.smtp_server_port,
    )


def non_flight_domain_to_dto(domain: NonFlightDomain) -> NonFlightDomainDTO:
    return NonFlightDomainDTO(domain=domain.domain, note=domain.note, created_at=domain.created_at)
