"""Use cases for the auth feature: setup, login (+ lockout), logout, me,
update-me, change-password.

2FA setup/enable/disable/verify is a separate concern — see twofa_service.py."""

import collections
import time

from .domain import LoginResult, UserSummary
from .errors import AuthError
from .repository import AuthRepository

_LOGIN_LOCKOUT_THRESHOLD = 5
_LOGIN_LOCKOUT_WINDOW = 10 * 60  # seconds

# Dummy hash used in login to prevent username enumeration via bcrypt timing
_DUMMY_HASH = "$2b$12$invalidhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

VALID_LOCALES = {"en", "pt-BR"}

# Must match ACCENTS in frontend/src/lib/accentStore.ts and the `data-accent`
# blocks in app.css. A value the stylesheet has no block for matches no preset
# and leaves the page on whatever the cascade fell back to, so it is rejected
# here rather than stored and puzzled over later.
VALID_ACCENTS = {"sky", "ocean", "dusk", "orchid", "graphite"}


class AuthService:
    def __init__(self, repository: AuthRepository | None = None):
        self._repository = repository or AuthRepository()
        self._login_failures: dict[str, list[float]] = collections.defaultdict(list)

    # -- Setup ---------------------------------------------------------------

    def setup(
        self, username: str, password: str, smtp_recipient_address: str | None
    ) -> tuple[UserSummary, str]:
        from .session import create_session_cookie, has_any_users, hash_password

        if has_any_users():
            raise AuthError("Setup already completed", 409)

        normalized = username.strip().lower()
        if len(normalized) < 4:
            raise AuthError("Username must be at least 4 characters", 400)
        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters", 400)

        try:
            user_id = self._repository.create_admin_user(
                normalized, hash_password(password), smtp_recipient_address
            )
        except Exception as e:
            raise AuthError("Could not create user", 400) from e

        from .audit_log import audit

        audit("setup", user_id=user_id, username=normalized)
        token = create_session_cookie(user_id)
        summary = UserSummary(
            id=user_id,
            username=normalized,
            is_admin=True,
            smtp_recipient_address=smtp_recipient_address,
            totp_enabled=False,
            locale="en",
            accent="sky",
        )
        return summary, token

    # -- Login -----------------------------------------------------------------

    def login(self, username: str, password: str, ip: str) -> LoginResult:
        from .session import create_pending_2fa_cookie, create_session_cookie, verify_password

        self._check_login_lockout(ip)

        user = self._repository.find_user_by_username(username.strip().lower())

        # Always run bcrypt to prevent username enumeration via timing differences
        password_hash = (user.password_hash if user else None) or _DUMMY_HASH
        password_ok = verify_password(password, password_hash)

        from .audit_log import audit

        if user is None or not password_ok:
            self._record_login_failure(ip)
            audit("login_failed", username=username, ip=ip)
            raise AuthError("Invalid username or password", 401)

        if user.totp_enabled:
            pending_token = create_pending_2fa_cookie(user.id)
            return LoginResult(requires_2fa=True, pending_token=pending_token)

        audit("login", user_id=user.id, username=user.username, ip=ip)
        session_token = create_session_cookie(user.id)
        summary = UserSummary(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            smtp_recipient_address=user.smtp_recipient_address,
            totp_enabled=user.totp_enabled,
            locale=user.locale,
            accent=user.accent,
        )
        return LoginResult(requires_2fa=False, user=summary, session_token=session_token)

    def _check_login_lockout(self, ip: str) -> None:
        # A demo instance publishes its password, so a failed attempt there is
        # a typo, not an attack — and the whole crowd usually shares one
        # apparent address behind the proxy, which would lock all of them out
        # together. The route's rate limit still bounds the endpoint.
        if self._demo_mode():
            return
        now = time.time()
        cutoff = now - _LOGIN_LOCKOUT_WINDOW
        self._login_failures[ip] = [t for t in self._login_failures[ip] if t > cutoff]
        if len(self._login_failures[ip]) >= _LOGIN_LOCKOUT_THRESHOLD:
            raise AuthError("Too many failed login attempts. Please try again later.", 429)

    def _record_login_failure(self, ip: str) -> None:
        # Nothing reads these in demo mode, and the pruning that keeps the list
        # bounded happens in the check we just skipped — so don't grow one.
        if self._demo_mode():
            return
        self._login_failures[ip].append(time.time())

    @staticmethod
    def _demo_mode() -> bool:
        from ..config import settings

        return settings.DEMO_MODE

    # -- Logout / me / update-me -----------------------------------------------

    def logout(self, token: str | None) -> None:
        from .session import revoke_session_cookie

        if token:
            revoke_session_cookie(token)

    def get_me(self, token: str | None) -> UserSummary:
        from .session import decode_session_cookie

        if not token:
            raise AuthError("Not authenticated", 401)
        user_id = decode_session_cookie(token)
        if user_id is None:
            raise AuthError("Invalid or expired session", 401)

        user = self._repository.get_user_summary(user_id)
        if user is None:
            raise AuthError("User not found", 401)
        return user

    def update_me(self, user_id: int, locale: str | None, accent: str | None = None) -> None:
        if locale is not None and locale not in VALID_LOCALES:
            raise AuthError(f"Invalid locale. Valid values: {sorted(VALID_LOCALES)}", 422)
        if accent is not None and accent not in VALID_ACCENTS:
            raise AuthError(f"Invalid accent. Valid values: {sorted(VALID_ACCENTS)}", 422)
        if locale is not None:
            self._repository.update_locale(user_id, locale)
        if accent is not None:
            self._repository.update_accent(user_id, accent)

    # -- Change password -------------------------------------------------------

    def change_password(
        self, user_id: int, current_password: str, new_password: str, totp_code: str | None
    ) -> None:
        import pyotp

        from .session import revoke_all_user_sessions, verify_password

        creds = self._repository.get_password_and_totp(user_id)
        if not creds or not verify_password(current_password, creds.password_hash):
            raise AuthError("Current password is incorrect", 400)

        if creds.totp_enabled:
            if not totp_code:
                raise AuthError("2FA code required", 400)
            assert creds.totp_secret is not None  # totp_enabled implies a secret was set
            if not pyotp.TOTP(creds.totp_secret).verify(totp_code, valid_window=1):
                raise AuthError("Invalid 2FA code", 400)

        if len(new_password) < 8:
            raise AuthError("New password must be at least 8 characters", 400)

        from .session import hash_password

        self._repository.update_password_hash(user_id, hash_password(new_password))
        # Invalidate all existing sessions so stolen cookies can't be reused
        revoke_all_user_sessions(user_id)

        from .audit_log import audit

        audit("password_changed", user_id=user_id)


auth_service = AuthService()
