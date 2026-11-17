"""
Black-box tests for API keys: minted from a signed-in session, then used with
no cookie at all, the way a script or another service would use one.
"""

import pytest
from fastapi.testclient import TestClient


def _mint(client: TestClient, scope: str = "read", **extra) -> dict:
    r = client.post("/api/api-keys", json={"name": "script", "scope": scope, **extra})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def bare_client(api_app):
    """A client with no session cookie — only what an integration would have."""
    with TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver") as c:
        yield c


def _bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


class TestManagingKeys:
    def test_nothing_exists_until_someone_creates_one(self, auth_client):
        assert auth_client.get("/api/api-keys").json() == []

    def test_the_value_is_shown_once_and_never_listed(self, auth_client):
        created = _mint(auth_client)
        assert created["key"].startswith("partiu_")
        assert created["scope"] == "read"

        (listed,) = auth_client.get("/api/api-keys").json()
        assert listed["id"] == created["id"]
        assert "key" not in listed
        assert created["key"] not in str(listed)
        assert listed["prefix"] == created["key"][: len(listed["prefix"])]

    def test_revoking_removes_it(self, auth_client):
        created = _mint(auth_client)
        assert auth_client.delete(f"/api/api-keys/{created['id']}").status_code == 204
        assert auth_client.get("/api/api-keys").json() == []
        assert auth_client.delete(f"/api/api-keys/{created['id']}").status_code == 404

    def test_invalid_input_is_refused(self, auth_client):
        assert auth_client.post("/api/api-keys", json={"name": ""}).status_code == 422
        assert (
            auth_client.post("/api/api-keys", json={"name": "x", "scope": "admin"}).status_code
            == 422
        )
        assert auth_client.post("/api/api-keys", json={"name": "   "}).status_code == 400

    def test_the_limit_is_a_409(self, auth_client):
        from backend.api_keys.service import MAX_KEYS_PER_USER

        for _ in range(MAX_KEYS_PER_USER):
            _mint(auth_client)
        r = auth_client.post("/api/api-keys", json={"name": "one too many"})
        assert r.status_code == 409

    def test_requires_being_signed_in(self, bare_client):
        assert bare_client.get("/api/api-keys").status_code == 401

    def test_refused_on_a_demo(self, auth_client, monkeypatch):
        from backend.config import settings

        monkeypatch.setattr(settings, "DEMO_MODE", True)
        assert auth_client.post("/api/api-keys", json={"name": "x"}).status_code == 403


class TestUsingAKey:
    def test_a_read_key_reads_without_a_cookie(self, auth_client, bare_client):
        secret = _mint(auth_client)["key"]
        assert bare_client.get("/api/trips").status_code == 401

        r = bare_client.get("/api/trips", headers=_bearer(secret))
        assert r.status_code == 200
        me = bare_client.get("/api/auth/me", headers=_bearer(secret))
        assert me.status_code == 200 and me.json()["username"] == "admin"

    def test_a_read_key_cannot_write(self, auth_client, bare_client):
        secret = _mint(auth_client)["key"]
        r = bare_client.post("/api/trips", json={"name": "Lisbon"}, headers=_bearer(secret))
        assert r.status_code == 403

    def test_a_write_key_can_write(self, auth_client, bare_client):
        secret = _mint(auth_client, scope="write")["key"]
        r = bare_client.post("/api/trips", json={"name": "Lisbon"}, headers=_bearer(secret))
        assert r.status_code in (200, 201), r.text

    def test_a_wrong_key_is_401_even_alongside_a_valid_cookie(self, auth_client):
        r = auth_client.get("/api/trips", headers=_bearer("partiu_not-a-real-key"))
        assert r.status_code == 401
        assert r.headers.get("www-authenticate") == "Bearer"

    def test_a_revoked_key_stops_working(self, auth_client, bare_client):
        created = _mint(auth_client)
        auth_client.delete(f"/api/api-keys/{created['id']}")
        assert bare_client.get("/api/trips", headers=_bearer(created["key"])).status_code == 401

    def test_a_key_cannot_mint_or_revoke_keys(self, auth_client, bare_client):
        created = _mint(auth_client, scope="write")
        headers = _bearer(created["key"])
        assert bare_client.get("/api/api-keys", headers=headers).status_code == 403
        assert (
            bare_client.post("/api/api-keys", json={"name": "x"}, headers=headers).status_code
            == 403
        )
        assert (
            bare_client.delete(f"/api/api-keys/{created['id']}", headers=headers).status_code == 403
        )

    def test_a_key_cannot_touch_the_account(self, auth_client, bare_client):
        headers = _bearer(_mint(auth_client, scope="write")["key"])
        r = bare_client.post(
            "/api/auth/change-password",
            json={"current_password": "password123", "new_password": "hijacked123"},
            headers=headers,
        )
        assert r.status_code == 403
        assert bare_client.get("/api/users", headers=headers).status_code == 403
        r = bare_client.post("/api/settings", json={"imap_host": "evil.example"}, headers=headers)
        assert r.status_code == 403

    def test_use_is_shown_in_the_list(self, auth_client, bare_client):
        created = _mint(auth_client)
        assert auth_client.get("/api/api-keys").json()[0]["last_used_at"] is None
        bare_client.get("/api/trips", headers=_bearer(created["key"]))
        assert auth_client.get("/api/api-keys").json()[0]["last_used_at"] is not None
