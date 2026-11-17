"""ApiKeyService: minting, authenticating, expiry, and the scope/endpoint rule."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.api_keys.service import (
    KEY_PREFIX,
    MAX_KEYS_PER_USER,
    ApiKeyLimitError,
    ApiKeyNotFoundError,
    ApiKeyService,
    hash_key,
    refusal_reason,
)


def _user(username: str = "alice") -> int:
    from backend.database import db_write

    with db_write() as conn:
        return conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, 'x')", (username,)
        ).lastrowid


class TestCreateKey:
    def test_returns_a_prefixed_secret_and_stores_only_its_hash(self, test_db):
        from backend.database import db_conn

        uid = _user()
        key, secret = ApiKeyService().create_key(uid, "  Home Assistant ", "read", None)

        assert secret.startswith(KEY_PREFIX)
        assert key.name == "Home Assistant"
        assert key.prefix == secret[: len(key.prefix)]
        assert key.expires_at is None
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key.id,)).fetchone()
        assert secret not in [str(v) for v in tuple(row)]
        assert row["key_hash"] == hash_key(secret)

    def test_two_keys_never_share_a_secret(self, test_db):
        uid = _user()
        svc = ApiKeyService()
        _, a = svc.create_key(uid, "a", "read", None)
        _, b = svc.create_key(uid, "b", "read", None)
        assert a != b

    def test_expiry_is_set_from_days(self, test_db):
        key, _ = ApiKeyService().create_key(_user(), "ci", "write", 30)
        assert key.expires_at is not None
        delta = datetime.fromisoformat(key.expires_at) - datetime.now(UTC)
        assert timedelta(days=29) < delta <= timedelta(days=30)

    def test_blank_name_is_refused(self, test_db):
        with pytest.raises(ValueError):
            ApiKeyService().create_key(_user(), "   ", "read", None)

    def test_unknown_scope_is_refused(self, test_db):
        with pytest.raises(ValueError):
            ApiKeyService().create_key(_user(), "x", "admin", None)

    def test_a_user_cannot_hold_more_than_the_limit(self, test_db):
        uid = _user()
        svc = ApiKeyService()
        for i in range(MAX_KEYS_PER_USER):
            svc.create_key(uid, f"k{i}", "read", None)
        with pytest.raises(ApiKeyLimitError):
            svc.create_key(uid, "one too many", "read", None)


class TestAuthenticate:
    def test_the_secret_resolves_to_its_key(self, test_db):
        svc = ApiKeyService()
        key, secret = svc.create_key(_user(), "x", "read", None)
        found = svc.authenticate(secret)
        assert found is not None and found.id == key.id

    def test_unknown_or_unprefixed_secrets_resolve_to_nothing(self, test_db):
        svc = ApiKeyService()
        _, secret = svc.create_key(_user(), "x", "read", None)
        assert svc.authenticate(secret + "x") is None
        assert svc.authenticate(secret[len(KEY_PREFIX) :]) is None
        assert svc.authenticate("") is None

    def test_an_expired_key_resolves_to_nothing(self, test_db):
        from backend.database import db_write

        svc = ApiKeyService()
        key, secret = svc.create_key(_user(), "x", "read", 1)
        past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        with db_write() as conn:
            conn.execute("UPDATE api_keys SET expires_at = ? WHERE id = ?", (past, key.id))
        assert svc.authenticate(secret) is None

    def test_use_is_recorded_but_not_on_every_request(self, test_db):
        from backend.database import db_write

        svc = ApiKeyService()
        key, secret = svc.create_key(_user(), "x", "read", None)
        first = svc.authenticate(secret)
        assert first is not None and first.last_used_at is not None
        second = svc.authenticate(secret)
        assert second is not None and second.last_used_at == first.last_used_at

        stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        with db_write() as conn:
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (stale, key.id))
        third = svc.authenticate(secret)
        assert third is not None and third.last_used_at != stale


class TestRevoke:
    def test_a_revoked_key_stops_working(self, test_db):
        svc = ApiKeyService()
        uid = _user()
        key, secret = svc.create_key(uid, "x", "read", None)
        svc.revoke_key(key.id, uid)
        assert svc.authenticate(secret) is None

    def test_someone_elses_key_cannot_be_revoked(self, test_db):
        svc = ApiKeyService()
        key, secret = svc.create_key(_user("alice"), "x", "read", None)
        with pytest.raises(ApiKeyNotFoundError):
            svc.revoke_key(key.id, _user("bob"))
        assert svc.authenticate(secret) is not None


class TestRefusalReason:
    @pytest.mark.parametrize("method", ["GET", "HEAD"])
    def test_read_keys_can_read(self, method):
        assert refusal_reason("read", method, "/api/trips") is None

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_read_keys_cannot_write(self, method):
        assert refusal_reason("read", method, "/api/trips/abc") is not None

    def test_write_keys_can_write_data(self):
        assert refusal_reason("write", "POST", "/api/trips") is None
        assert refusal_reason("write", "DELETE", "/api/trips/abc/packing/1") is None

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/api-keys"),
            ("POST", "/api/api-keys"),
            ("DELETE", "/api/api-keys/3"),
            ("POST", "/api/auth/change-password"),
            ("POST", "/api/auth/2fa/enable"),
            ("POST", "/api/auth/2fa/disable"),
            ("GET", "/api/auth/2fa/setup"),
            ("PATCH", "/api/auth/me"),
            ("POST", "/api/auth/logout"),
            ("GET", "/api/users"),
            ("DELETE", "/api/users/2"),
            ("POST", "/api/settings"),
            ("POST", "/api/settings/test-imap"),
            ("POST", "/api/settings/admin/non-flight-domains"),
            # Path spellings that still route to the same handler.
            ("POST", "//api//api-keys/"),
            ("POST", "/api/settings/"),
        ],
    )
    def test_account_surfaces_are_out_of_reach_at_any_scope(self, method, path):
        assert refusal_reason("write", method, path) is not None

    def test_who_am_i_and_reading_settings_stay_open(self):
        assert refusal_reason("read", "GET", "/api/auth/me") is None
        assert refusal_reason("read", "GET", "/api/settings") is None

    def test_prefix_lookalikes_are_not_caught(self):
        assert refusal_reason("read", "GET", "/api/users-stats") is None
