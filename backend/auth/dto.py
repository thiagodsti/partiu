"""Request/response DTOs for the auth HTTP API (routes.py)."""

from pydantic import BaseModel


class SetupRequestDTO(BaseModel):
    username: str
    password: str
    smtp_recipient_address: str | None = None


class LoginRequestDTO(BaseModel):
    username: str
    password: str


class ChangePasswordRequestDTO(BaseModel):
    current_password: str
    new_password: str
    totp_code: str | None = None


class TwoFAVerifyRequestDTO(BaseModel):
    code: str


class TwoFAEnableRequestDTO(BaseModel):
    code: str


class TwoFADisableRequestDTO(BaseModel):
    code: str | None = None
    password: str | None = None


class UpdateMeRequestDTO(BaseModel):
    locale: str | None = None


class UserResponseDTO(BaseModel):
    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None
    totp_enabled: bool
    locale: str


class MeResponseDTO(UserResponseDTO):
    announcement: str = ""


class RequiresTwoFADTO(BaseModel):
    requires_2fa: bool = True


class TwoFASetupResponseDTO(BaseModel):
    secret: str
    uri: str


class OkDTO(BaseModel):
    ok: bool
