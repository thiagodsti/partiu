"""
Symmetric encryption for sensitive data stored at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a 32-byte key derived
from SECRET_KEY via SHA-256. Encrypted values are Fernet tokens
(base64url strings starting with 'gAAAAA').

Usage:
    from .crypto import encrypt, decrypt
    stored = encrypt(plaintext)   # call before writing to DB
    plain  = decrypt(stored)      # call after reading from DB
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        from .config import settings

        key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
    return _fernet


def encrypt(value: str) -> str:
    """Encrypt a plaintext string and return a Fernet token."""
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """
    Decrypt a Fernet-encrypted string.

    If the value is not a valid token (legacy plaintext from before
    encryption was introduced), return it unchanged so old data still
    works transparently until it is re-saved.
    """
    if not value:
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        return value  # legacy plaintext — return as-is


def is_encrypted(value: str) -> bool:
    """Return True if the value looks like a Fernet token (already encrypted)."""
    return bool(value) and value.startswith("gAAAAA") and len(value) > 80
