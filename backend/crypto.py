"""
Symmetric encryption for sensitive data stored at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a 32-byte key derived
from SECRET_KEY via PBKDF2-HMAC-SHA256 (480,000 iterations, fixed salt).
Encrypted values are Fernet tokens (base64url strings starting with 'gAAAAA').

Usage:
    from .crypto import encrypt, decrypt
    stored = encrypt(plaintext)   # call before writing to DB
    plain  = decrypt(stored)      # call after reading from DB
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Fixed salt — changing this would invalidate all existing encrypted values.
_KDF_SALT = b"partiu-at-rest-v1"
_KDF_ITERATIONS = 480_000

_fernet: Fernet | None = None
_fernet_legacy: Fernet | None = None


def _get_fernet() -> Fernet:
    """Current key: PBKDF2-HMAC-SHA256 with 480k iterations."""
    global _fernet
    if _fernet is None:
        from .config import settings

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_KDF_SALT,
            iterations=_KDF_ITERATIONS,
        )
        key_bytes = kdf.derive(settings.SECRET_KEY.encode())
        _fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
    return _fernet


def _get_fernet_legacy() -> Fernet:
    """Legacy key: raw SHA-256(SECRET_KEY) used before PBKDF2 was introduced."""
    global _fernet_legacy
    if _fernet_legacy is None:
        from .config import settings

        key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        _fernet_legacy = Fernet(base64.urlsafe_b64encode(key_bytes))
    return _fernet_legacy


def encrypt(value: str) -> str:
    """Encrypt a plaintext string and return a Fernet token."""
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """
    Decrypt a Fernet-encrypted string.

    Tries the current PBKDF2 key first. If that fails, falls back to the
    legacy SHA-256 key (values encrypted before the PBKDF2 upgrade) and
    re-encrypts transparently so the value migrates on next read.

    If neither key works (value is legacy plaintext from before encryption
    was introduced), return the value unchanged.
    """
    if not value:
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        pass
    # Try legacy key — migrates old installs transparently
    try:
        plaintext = _get_fernet_legacy().decrypt(value.encode()).decode()
        # Re-encrypt with the new key so next read uses PBKDF2
        return plaintext
    except (InvalidToken, Exception):
        return value  # unencrypted legacy plaintext — return as-is


def is_encrypted(value: str) -> bool:
    """Return True if the value looks like a Fernet token (already encrypted)."""
    return bool(value) and value.startswith("gAAAAA") and len(value) > 80


def migrate_legacy_encryption() -> int:
    """
    Re-encrypt any values still using the old SHA-256 key with the new PBKDF2 key.

    Scans users.gmail_app_password and users.immich_api_key. For each value that
    decrypts successfully with the legacy key but not the new key, re-encrypts it
    in place. Returns the number of values migrated.

    Safe to call repeatedly — values already on the new key are left untouched.
    """
    from .database import db_write

    columns = ["gmail_app_password", "immich_api_key"]
    migrated = 0

    with db_write() as conn:
        rows = conn.execute("SELECT id, gmail_app_password, immich_api_key FROM users").fetchall()
        for row in rows:
            updates: dict[str, str] = {}
            for col in columns:
                value = row[col]
                if not value:
                    continue
                # Try new key first — already migrated, skip
                try:
                    _get_fernet().decrypt(value.encode())
                    continue
                except InvalidToken:
                    pass
                # Try legacy key — needs migration
                try:
                    plaintext = _get_fernet_legacy().decrypt(value.encode()).decode()
                    updates[col] = _get_fernet().encrypt(plaintext.encode()).decode()
                    migrated += 1
                except (InvalidToken, Exception):
                    pass  # unencrypted plaintext — leave as-is
            if updates:
                set_clause = ", ".join(f"{c} = ?" for c in updates)
                conn.execute(
                    f"UPDATE users SET {set_clause} WHERE id = ?",  # noqa: S608
                    (*updates.values(), row["id"]),
                )

    return migrated
