"""Tests for backend/crypto.py — symmetric encryption utilities."""

import os

import pytest


@pytest.fixture(autouse=True)
def reset_fernet():
    """Reset the Fernet singleton before each test so SECRET_KEY patching takes effect."""
    import backend.crypto as crypto_mod

    crypto_mod._fernet = None
    yield
    crypto_mod._fernet = None


class TestEncrypt:
    def test_encrypt_returns_string(self):
        from backend.crypto import encrypt

        result = encrypt("my-secret-password")
        assert isinstance(result, str)

    def test_encrypt_produces_fernet_token(self):
        from backend.crypto import encrypt

        result = encrypt("my-secret-password")
        assert result.startswith("gAAAAA")
        assert len(result) > 80

    def test_encrypt_empty_string_returns_empty(self):
        from backend.crypto import encrypt

        assert encrypt("") == ""

    def test_encrypt_produces_different_ciphertext_each_time(self):
        """Fernet uses a random IV so the same plaintext encrypts differently."""
        from backend.crypto import encrypt

        a = encrypt("same-value")
        b = encrypt("same-value")
        assert a != b  # different ciphertexts

    def test_encrypt_preserves_special_characters(self):
        from backend.crypto import decrypt, encrypt

        original = "p@$$w0rd!#%^&*()"
        assert decrypt(encrypt(original)) == original


class TestDecrypt:
    def test_decrypt_encrypted_value(self):
        from backend.crypto import decrypt, encrypt

        original = "gmail-app-password-123"
        assert decrypt(encrypt(original)) == original

    def test_decrypt_empty_returns_empty(self):
        from backend.crypto import decrypt

        assert decrypt("") == ""

    def test_decrypt_plaintext_returns_plaintext(self):
        """Legacy plaintext values (before encryption was added) must pass through."""
        from backend.crypto import decrypt

        assert decrypt("plaintext-value") == "plaintext-value"

    def test_decrypt_long_string(self):
        from backend.crypto import decrypt, encrypt

        original = "a" * 500
        assert decrypt(encrypt(original)) == original

    def test_decrypt_unicode(self):
        from backend.crypto import decrypt, encrypt

        original = "pässwörd-日本語"
        assert decrypt(encrypt(original)) == original


class TestIsEncrypted:
    def test_encrypted_value_detected(self):
        from backend.crypto import encrypt, is_encrypted

        assert is_encrypted(encrypt("test"))

    def test_plaintext_not_detected(self):
        from backend.crypto import is_encrypted

        assert not is_encrypted("plaintext")

    def test_empty_string_not_encrypted(self):
        from backend.crypto import is_encrypted

        assert not is_encrypted("")

    def test_short_gaaaaa_not_encrypted(self):
        from backend.crypto import is_encrypted

        assert not is_encrypted("gAAAAA")  # too short to be a real Fernet token


class TestRoundtrip:
    def test_multiple_fields_roundtrip(self):
        from backend.crypto import decrypt, encrypt

        fields = {
            "gmail_app_password": "abcd efgh ijkl mnop",
            "immich_api_key": "eyJhbGciOiJIUzI1NiJ9.abc",
        }
        encrypted = {k: encrypt(v) for k, v in fields.items()}
        decrypted = {k: decrypt(v) for k, v in encrypted.items()}
        assert decrypted == fields


class TestMigrateLegacyEncryption:
    def _seed_user(self, db_path: str, **column_values) -> int:
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('u', 'h', 0)")
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if column_values:
            set_clause = ", ".join(f"{k} = ?" for k in column_values)
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id = ?",  # noqa: S608
                (*column_values.values(), user_id),
            )
        conn.commit()
        conn.close()
        return user_id

    def test_migrates_legacy_encrypted_value(self, test_db):
        from backend.crypto import _get_fernet, _get_fernet_legacy, migrate_legacy_encryption
        from backend.users.repository import UserRepository

        legacy_token = _get_fernet_legacy().encrypt(b"my-app-password").decode()
        user_id = self._seed_user(test_db, gmail_app_password=legacy_token)

        migrated = migrate_legacy_encryption()
        assert migrated == 1

        [row] = [r for r in UserRepository().list_credential_columns() if r["id"] == user_id]
        # Re-encrypted value now decrypts with the current key to the same plaintext.
        assert _get_fernet().decrypt(row["gmail_app_password"].encode()) == b"my-app-password"

    def test_idempotent_second_run_migrates_nothing(self, test_db):
        from backend.crypto import _get_fernet_legacy, migrate_legacy_encryption

        legacy_token = _get_fernet_legacy().encrypt(b"my-app-password").decode()
        self._seed_user(test_db, gmail_app_password=legacy_token)

        migrate_legacy_encryption()
        assert migrate_legacy_encryption() == 0

    def test_already_current_key_not_migrated(self, test_db):
        from backend.crypto import encrypt, migrate_legacy_encryption

        self._seed_user(test_db, gmail_app_password=encrypt("already-current"))

        assert migrate_legacy_encryption() == 0

    def test_plaintext_value_left_alone(self, test_db):
        from backend.crypto import migrate_legacy_encryption
        from backend.users.repository import UserRepository

        user_id = self._seed_user(test_db, gmail_app_password="plaintext-legacy-value")

        assert migrate_legacy_encryption() == 0
        [row] = [r for r in UserRepository().list_credential_columns() if r["id"] == user_id]
        assert row["gmail_app_password"] == "plaintext-legacy-value"

    def test_migrates_both_credential_columns(self, test_db):
        from backend.crypto import _get_fernet, _get_fernet_legacy, migrate_legacy_encryption
        from backend.users.repository import UserRepository

        user_id = self._seed_user(
            test_db,
            gmail_app_password=_get_fernet_legacy().encrypt(b"gmail-secret").decode(),
            immich_api_key=_get_fernet_legacy().encrypt(b"immich-secret").decode(),
        )

        assert migrate_legacy_encryption() == 2

        [row] = [r for r in UserRepository().list_credential_columns() if r["id"] == user_id]
        assert _get_fernet().decrypt(row["gmail_app_password"].encode()) == b"gmail-secret"
        assert _get_fernet().decrypt(row["immich_api_key"].encode()) == b"immich-secret"
