"""
Authentication routes: setup, login, logout, me, change-password, 2FA.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..limiter import limiter
from . import auth_service, twofa_service
from .access import refuse_on_demo
from .domain import UserSummary
from .dto import (
    ChangePasswordRequestDTO,
    LoginRequestDTO,
    MeResponseDTO,
    OkDTO,
    PublicConfigDTO,
    RequiresTwoFADTO,
    SetupRequestDTO,
    TwoFADisableRequestDTO,
    TwoFAEnableRequestDTO,
    TwoFASetupResponseDTO,
    TwoFAVerifyRequestDTO,
    UpdateMeRequestDTO,
    UserResponseDTO,
)
from .errors import AuthError
from .mappers import user_summary_to_dto, user_summary_to_me_dto
from .session import get_current_user, has_any_users

SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "true").lower() != "false"

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _login_rate_limit() -> str:
    """The per-IP ceiling on sign-in attempts, resolved per request.

    5/minute is right for a private install, where the only person behind an
    address is the owner. A public demo is the opposite: everyone arrives with
    the same published username, and behind a reverse proxy they may all share
    one apparent address, so the sixth visitor in a minute was being turned
    away with a 429 for the crime of being sixth. Demo mode raises the ceiling
    rather than removing it — a bound the crowd cannot reach still bounds a
    script — and `AuthService` skips its own per-IP lockout for the same reason.
    """
    from ..config import settings

    return "120/minute" if settings.DEMO_MODE else "5/minute"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        max_age=30 * 86400,
    )


def _me_dto(summary: UserSummary) -> MeResponseDTO:
    """The full sign-in response: the user plus the server config the SPA needs."""
    from ..config import settings

    return user_summary_to_me_dto(
        summary, settings.ANNOUNCEMENT, settings.CARTO_API_KEY, settings.DEMO_MODE
    )


@router.post("/setup", response_model=UserResponseDTO)
@limiter.limit("5/minute")
def setup(request: Request, body: SetupRequestDTO, response: Response):
    try:
        summary, token = auth_service.setup(
            body.username, body.password, body.smtp_recipient_address
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    _set_session_cookie(response, token)
    return user_summary_to_dto(summary)


@router.post("/login")
@limiter.limit(_login_rate_limit)
def login(request: Request, body: LoginRequestDTO, response: Response):
    ip = request.client.host if request.client else "unknown"
    try:
        result = auth_service.login(body.username, body.password, ip)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    if result.requires_2fa:
        assert result.pending_token is not None
        resp = JSONResponse(RequiresTwoFADTO().model_dump(), status_code=200)
        resp.set_cookie(
            "pending_2fa",
            result.pending_token,
            httponly=True,
            samesite="lax",
            secure=SECURE_COOKIES,
            max_age=300,
        )
        return resp

    assert result.session_token is not None and result.user is not None
    _set_session_cookie(response, result.session_token)
    # The me-shaped DTO, not the bare user: signing in does not remount the SPA,
    # so whatever this response omits stays missing until the next full load.
    # `announcement`, `carto_api_key` and `demo` all only existed on /auth/me,
    # which is why a demo's banner appeared only after a hard refresh — and why
    # the trip map fell back to OSM tiles for the rest of the session.
    return _me_dto(result.user)


@router.post("/2fa/verify", response_model=MeResponseDTO)
@limiter.limit("10/minute")
def verify_2fa(request: Request, body: TwoFAVerifyRequestDTO, response: Response):
    pending_token = request.cookies.get("pending_2fa")
    ip = request.client.host if request.client else None
    try:
        summary, session_token = twofa_service.verify_2fa(pending_token, body.code, ip)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    response.delete_cookie("pending_2fa", httponly=True, samesite="lax", secure=True)
    _set_session_cookie(response, session_token)
    # Same shape as the password-only path — this branch signs in just as
    # completely, so it must hand back just as much.
    return _me_dto(summary)


@router.get("/2fa/setup", response_model=TwoFASetupResponseDTO)
def setup_2fa(user: dict = Depends(get_current_user)):
    try:
        result = twofa_service.setup_2fa(user)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return TwoFASetupResponseDTO(secret=result.secret, uri=result.uri)


@router.post("/2fa/enable", response_model=OkDTO)
def enable_2fa(body: TwoFAEnableRequestDTO, user: dict = Depends(get_current_user)):
    refuse_on_demo("Enabling two-factor authentication")
    try:
        twofa_service.enable_2fa(user["id"], body.code)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return OkDTO(ok=True)


@router.post("/2fa/disable", response_model=OkDTO)
def disable_2fa(body: TwoFADisableRequestDTO, user: dict = Depends(get_current_user)):
    try:
        twofa_service.disable_2fa(user["id"], body.code, body.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return OkDTO(ok=True)


@router.post("/logout", response_model=OkDTO)
def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    auth_service.logout(token)
    response.delete_cookie("session", httponly=True, samesite="lax", secure=True)
    return OkDTO(ok=True)


@router.get("/me", response_model=MeResponseDTO)
def me(request: Request):
    if not has_any_users():
        return JSONResponse({"detail": "Setup required", "setup_required": True}, status_code=503)

    token = request.cookies.get("session")
    try:
        summary = auth_service.get_me(token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    return _me_dto(summary)


@router.get("/public-config", response_model=PublicConfigDTO)
def public_config():
    """Unauthenticated: the handful of server facts the login page needs.

    Only the demo credentials live here, and only while DEMO_MODE is on — off,
    the response is three empty fields, so an ordinary install leaks nothing.
    """
    from ..config import settings

    if not settings.DEMO_MODE:
        return PublicConfigDTO()
    return PublicConfigDTO(
        demo=True,
        demo_username=settings.DEMO_USERNAME,
        demo_password=settings.DEMO_PASSWORD,
    )


@router.patch("/me", response_model=OkDTO)
def update_me(body: UpdateMeRequestDTO, user: dict = Depends(get_current_user)):
    try:
        auth_service.update_me(user["id"], body.locale, body.accent)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return OkDTO(ok=True)


@router.post("/change-password", response_model=OkDTO)
def change_password(body: ChangePasswordRequestDTO, user: dict = Depends(get_current_user)):
    refuse_on_demo("Changing the password")
    try:
        auth_service.change_password(
            user["id"], body.current_password, body.new_password, body.totp_code
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return OkDTO(ok=True)
