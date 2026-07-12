"""Domain objects for the auth feature (setup/login/2FA/logout/me/change-password).

Not to be confused with the plain ``dict`` shape ``get_current_user`` (session.py)
returns and every other feature's routes take as ``user: dict`` — that convention
predates this refactor and changing it would ripple into ~15 other files, so it's
left as-is. These objects are internal to this feature's own service/repository.
"""

from dataclasses import dataclass


@dataclass
class AuthUser:
    """A user row as needed internally by auth flows — may include secrets
    (password_hash, totp_secret) depending on which repository method built it."""

    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None
    totp_enabled: bool
    locale: str
    password_hash: str | None = None
    totp_secret: str | None = None


@dataclass
class UserSummary:
    """The public-facing user shape returned by setup/login/2fa-verify/me."""

    id: int
    username: str
    is_admin: bool
    smtp_recipient_address: str | None
    totp_enabled: bool
    locale: str


@dataclass
class LoginResult:
    requires_2fa: bool
    pending_token: str | None = None
    user: UserSummary | None = None
    session_token: str | None = None


@dataclass
class TwoFASetup:
    secret: str
    uri: str


@dataclass
class PasswordAndTotp:
    """The subset of a user row needed by change-password and 2FA-disable."""

    password_hash: str
    totp_secret: str | None
    totp_enabled: bool
