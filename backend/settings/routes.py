"""
Settings routes — read/write Gmail credentials and app configuration.
Per-user settings stored in users table. Global settings stored in global_settings table.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import get_current_user, require_admin
from ..limiter import limiter
from . import settings_service
from .dto import (
    AddDomainRequestDTO,
    AddDomainResponseDTO,
    AirportCountDTO,
    AirportReloadDTO,
    NonFlightDomainDTO,
    OkDTO,
    OkMessageDTO,
    SettingsDTO,
    SettingsUpdateDTO,
    TestImapRequestDTO,
)
from .errors import AdminRequiredError, SmtpConflictError, ValidationError
from .mappers import non_flight_domain_to_dto, settings_to_dto

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsDTO)
def get_settings(user: dict = Depends(get_current_user)):
    """Return current settings (password masked). Per-user IMAP + global config for admins."""
    return settings_to_dto(settings_service.get_settings(user))


@router.post("", response_model=OkMessageDTO)
@limiter.limit("20/minute")
def update_settings(
    request: Request, body: SettingsUpdateDTO, user: dict = Depends(get_current_user)
):
    """
    Update settings.
    Per-user settings are stored in the users table.
    Global settings are stored in the global_settings table (admin only).
    """
    try:
        settings_service.update_settings(user, body.model_dump(exclude_none=True))
    except SmtpConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AdminRequiredError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OkMessageDTO(ok=True, message="Settings saved")


@router.post("/test-imap", response_model=OkMessageDTO)
@limiter.limit("5/minute")
def test_imap(request: Request, body: TestImapRequestDTO, user: dict = Depends(get_current_user)):
    """Try connecting and authenticating to the IMAP server with the given (or stored) credentials."""
    try:
        message = settings_service.test_imap(
            user, body.imap_host, body.imap_port, body.gmail_address, body.gmail_app_password
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OkMessageDTO(ok=True, message=message)


@router.post("/test-immich", response_model=OkMessageDTO)
@limiter.limit("5/minute")
async def test_immich(request: Request, user: dict = Depends(get_current_user)):
    """Test the configured Immich connection."""
    try:
        message = await settings_service.test_immich(user)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return OkMessageDTO(ok=True, message=message)


@router.get("/airports/count", response_model=AirportCountDTO)
def get_airport_count(user: dict = Depends(get_current_user)):
    """Return the number of airports loaded in the database."""
    return AirportCountDTO(count=settings_service.get_airport_count())


@router.get("/admin/non-flight-domains", response_model=list[NonFlightDomainDTO])
def list_blocked_domains(user: dict = Depends(require_admin)):
    return [non_flight_domain_to_dto(d) for d in settings_service.list_non_flight_domains()]


@router.post("/admin/non-flight-domains", response_model=AddDomainResponseDTO)
def add_blocked_domain(body: AddDomainRequestDTO, user: dict = Depends(require_admin)):
    domain = settings_service.add_non_flight_domain(body.domain, body.note)
    return AddDomainResponseDTO(ok=True, domain=domain)


@router.delete("/admin/non-flight-domains/{domain:path}", response_model=OkDTO)
def delete_blocked_domain(domain: str, user: dict = Depends(require_admin)):
    settings_service.remove_non_flight_domain(domain)
    return OkDTO(ok=True)


@router.post("/airports/reload", response_model=AirportReloadDTO)
def reload_airports(user: dict = Depends(require_admin)):
    """Re-load airports from data/airports.csv. Admin only."""
    count = settings_service.reload_airports()
    return AirportReloadDTO(ok=True, count=count)
