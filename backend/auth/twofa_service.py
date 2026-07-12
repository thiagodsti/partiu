"""2FA use cases: verify (completes a pending login), setup/enable/disable (for
an already-authenticated user), and TOTP lockout — kept separate from
service.py (which owns setup/login/logout/me/change-password)."""

from .domain import TwoFASetup, UserSummary
from .errors import AuthError
from .repository import AuthRepository

_TOTP_LOCKOUT_THRESHOLD = 5
_TOTP_LOCKOUT_WINDOW_MINUTES = 15


class TwoFAService:
    def __init__(self, repository: AuthRepository | None = None):
        self._repository = repository or AuthRepository()

    # -- 2FA verify (completes a pending login) -------------------------------

    def verify_2fa(
        self, pending_token: str | None, code: str, ip: str | None
    ) -> tuple[UserSummary, str]:
        import pyotp

        from .session import create_session_cookie, decode_pending_2fa_cookie

        if not pending_token:
            raise AuthError("No pending 2FA session", 401)
        user_id = decode_pending_2fa_cookie(pending_token)
        if user_id is None:
            raise AuthError("Pending 2FA session expired or invalid", 401)

        user = self._repository.get_user_with_totp_secret(user_id)
        if user is None:
            raise AuthError("User not found", 401)
        if not user.totp_secret:
            raise AuthError("2FA not configured", 400)

        self._check_totp_lockout(user_id)

        success = pyotp.TOTP(user.totp_secret).verify(code, valid_window=1)
        self._repository.record_totp_attempt(user_id, success)

        from .audit_log import audit

        if not success:
            audit("2fa_failed", user_id=user_id, ip=ip)
            raise AuthError("Invalid 2FA code", 401)

        audit("login_2fa", user_id=user_id, username=user.username, ip=ip)
        session_token = create_session_cookie(user.id)
        summary = UserSummary(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            smtp_recipient_address=user.smtp_recipient_address,
            totp_enabled=user.totp_enabled,
            locale=user.locale,
        )
        return summary, session_token

    def _check_totp_lockout(self, user_id: int) -> None:
        recent_failures = self._repository.count_recent_totp_failures(
            user_id, _TOTP_LOCKOUT_WINDOW_MINUTES
        )
        if recent_failures >= _TOTP_LOCKOUT_THRESHOLD:
            raise AuthError("Too many failed 2FA attempts. Please try again later.", 429)

    # -- 2FA setup / enable / disable (for an already-authenticated user) -----

    def setup_2fa(self, user: dict) -> TwoFASetup:
        import pyotp

        if user.get("totp_enabled"):
            raise AuthError("2FA already enabled", 400)

        secret = self._repository.get_totp_secret(user["id"])
        if not secret:
            secret = pyotp.random_base32()
            self._repository.set_totp_secret(user["id"], secret)

        uri = pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="Partiu")
        return TwoFASetup(secret=secret, uri=uri)

    def enable_2fa(self, user_id: int, code: str) -> None:
        import pyotp

        from .session import revoke_all_user_sessions

        secret = self._repository.get_totp_secret(user_id)
        if not secret:
            raise AuthError("Run setup first", 400)
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise AuthError("Invalid code", 400)

        self._repository.set_totp_enabled(user_id)
        # Revoke existing sessions so they must re-authenticate through 2FA
        revoke_all_user_sessions(user_id)

        from .audit_log import audit

        audit("2fa_enabled", user_id=user_id)

    def disable_2fa(self, user_id: int, code: str | None, password: str | None) -> None:
        import pyotp

        from .session import revoke_all_user_sessions, verify_password

        if not code and not password:
            raise AuthError("Provide a TOTP code or current password", 400)

        creds = self._repository.get_password_and_totp(user_id)
        if not creds:
            raise AuthError("User not found", 400)

        valid = False
        if code and creds.totp_secret:
            valid = pyotp.TOTP(creds.totp_secret).verify(code, valid_window=1)
        if not valid and password:
            valid = verify_password(password, creds.password_hash)
        if not valid:
            raise AuthError("Invalid code or password", 400)

        self._repository.clear_totp(user_id)
        revoke_all_user_sessions(user_id)

        from .audit_log import audit

        audit("2fa_disabled", user_id=user_id)


twofa_service = TwoFAService()
