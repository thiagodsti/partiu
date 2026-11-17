"""Use cases for personal API keys: minting, authenticating, and what a key may reach."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from ..utils import now_iso
from .domain import ApiKey
from .repository import ApiKeyRepository

# Recognisable in a config file, a log line or a secret scanner's rules.
KEY_PREFIX = "partiu_"
# Enough of the key to tell two apart in the list, far too little to use.
_DISPLAY_PREFIX_LEN = len(KEY_PREFIX) + 6
MAX_KEYS_PER_USER = 20
# A write per request would take the database's write lock on every API call;
# "last used" is only ever read at the granularity of a day anyway.
_TOUCH_INTERVAL = timedelta(minutes=5)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ApiKeyLimitError(Exception):
    """Raised when the user already holds MAX_KEYS_PER_USER keys."""


class ApiKeyNotFoundError(Exception):
    """Raised when the key does not exist or belongs to someone else."""


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _is_session_only(method: str, path: str) -> bool:
    """Surfaces that guard the account itself, which no key reaches at any scope.

    A key is a credential that lives in someone's script or config file; if it
    leaks, the damage must stop at the data. So a key can never mint or revoke
    keys (that would make revoking a leaked one pointless), never touch the
    password, 2FA or sessions, never manage accounts, and never rewrite the
    settings — those hold the IMAP and Immich credentials, and pointing the IMAP
    host somewhere else is enough to make the next sync hand the stored password
    to whoever chose the host. Reading `/api/auth/me` stays allowed, because
    "who does this key belong to" is the first thing an integration asks.
    """
    path = "/" + "/".join(p for p in path.split("/") if p)
    if path == "/api/api-keys" or path.startswith("/api/api-keys/"):
        return True
    if path.startswith("/api/auth/"):
        return not (method in _SAFE_METHODS and path == "/api/auth/me")
    if path == "/api/users" or path.startswith("/api/users/"):
        return True
    if path == "/api/settings" or path.startswith("/api/settings/"):
        return method not in _SAFE_METHODS
    return False


def refusal_reason(scope: str, method: str, path: str) -> str | None:
    """Why a key of this scope may not make this request, or None if it may."""
    method = method.upper()
    if _is_session_only(method, path):
        return "API keys cannot be used for this endpoint; sign in instead"
    if scope != "write" and method not in _SAFE_METHODS:
        return "This API key is read-only"
    return None


class ApiKeyService:
    def __init__(self, repository: ApiKeyRepository | None = None):
        self._repository = repository or ApiKeyRepository()

    def list_keys(self, user_id: int) -> list[ApiKey]:
        return self._repository.list_for_user(user_id)

    def create_key(
        self, user_id: int, name: str, scope: str, expires_in_days: int | None
    ) -> tuple[ApiKey, str]:
        """Mint a key. Returns it with its secret — the only time the secret exists outside the caller."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Name cannot be empty")
        if scope not in ("read", "write"):
            raise ValueError("Scope must be 'read' or 'write'")
        secret = KEY_PREFIX + secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = (
            (now + timedelta(days=expires_in_days)).isoformat() if expires_in_days else None
        )
        key = self._repository.create_within_limit(
            user_id=user_id,
            name=clean_name,
            prefix=secret[:_DISPLAY_PREFIX_LEN],
            key_hash=hash_key(secret),
            scope=scope,
            created_at=now.isoformat(),
            expires_at=expires_at,
            limit=MAX_KEYS_PER_USER,
        )
        if key is None:
            raise ApiKeyLimitError(user_id)
        return key, secret

    def revoke_key(self, key_id: int, user_id: int) -> None:
        if not self._repository.delete(key_id, user_id):
            raise ApiKeyNotFoundError(key_id)

    def authenticate(self, secret: str) -> ApiKey | None:
        """The live key this secret belongs to, or None (unknown, malformed or expired)."""
        if not secret.startswith(KEY_PREFIX):
            return None
        key = self._repository.find_by_hash(hash_key(secret))
        if key is None:
            return None
        now = datetime.now(UTC)
        if key.expires_at and datetime.fromisoformat(key.expires_at) <= now:
            return None
        if key.last_used_at is None or (
            now - datetime.fromisoformat(key.last_used_at) >= _TOUCH_INTERVAL
        ):
            key.last_used_at = now_iso()
            self._repository.touch(key.id, key.last_used_at)
        return key


api_key_service = ApiKeyService()
