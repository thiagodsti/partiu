"""Tests for /api/users admin routes."""

import pytest


class TestListUsers:
    def test_list_users_as_admin(self, auth_client):
        r = auth_client.get("/api/users")
        assert r.status_code == 200
        users = r.json()
        assert len(users) == 1
        assert users[0]["username"] == "admin"

    def test_list_users_non_admin_forbidden(self, auth_client, api_app):
        # Create a non-admin user and log in as them
        auth_client.post(
            "/api/users", json={"username": "regular", "password": "password123", "is_admin": False}
        )
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "regular", "password": "password123"})
            r = c.get("/api/users")
            assert r.status_code == 403

    def test_list_users_unauthenticated(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.get("/api/users")
        assert r.status_code == 401


class TestCreateUser:
    def test_create_regular_user(self, auth_client):
        r = auth_client.post("/api/users", json={"username": "alice", "password": "password123"})
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "alice"
        assert data["is_admin"] is False

    def test_create_admin_user(self, auth_client):
        r = auth_client.post(
            "/api/users", json={"username": "bob", "password": "password123", "is_admin": True}
        )
        assert r.status_code == 200
        assert r.json()["is_admin"] is True

    def test_create_user_with_smtp(self, auth_client):
        r = auth_client.post(
            "/api/users",
            json={
                "username": "alice",
                "password": "password123",
                "smtp_recipient_address": "alice@example.com",
            },
        )
        assert r.status_code == 200
        assert r.json()["smtp_recipient_address"] == "alice@example.com"

    def test_create_user_username_too_short(self, auth_client):
        r = auth_client.post("/api/users", json={"username": "a", "password": "password123"})
        assert r.status_code == 400

    def test_create_user_password_too_short(self, auth_client):
        r = auth_client.post("/api/users", json={"username": "alice", "password": "short"})
        assert r.status_code == 400

    def test_create_duplicate_username(self, auth_client):
        auth_client.post("/api/users", json={"username": "alice", "password": "password123"})
        r = auth_client.post("/api/users", json={"username": "alice", "password": "password123"})
        assert r.status_code == 400

    def test_create_user_non_admin_forbidden(self, auth_client, api_app):
        auth_client.post("/api/users", json={"username": "regular", "password": "password123"})
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "regular", "password": "password123"})
            r = c.post("/api/users", json={"username": "hacker", "password": "password123"})
            assert r.status_code == 403

    def test_users_appear_in_list(self, auth_client):
        auth_client.post("/api/users", json={"username": "alice", "password": "password123"})
        r = auth_client.get("/api/users")
        usernames = [u["username"] for u in r.json()]
        assert "alice" in usernames


class TestUpdateUser:
    def _create_user(self, auth_client, username="alice"):
        r = auth_client.post("/api/users", json={"username": username, "password": "password123"})
        return r.json()["id"]

    def test_update_user_smtp(self, auth_client):
        uid = self._create_user(auth_client)
        r = auth_client.patch(
            f"/api/users/{uid}", json={"smtp_recipient_address": "alice@test.com"}
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_update_user_promote_to_admin(self, auth_client):
        uid = self._create_user(auth_client)
        r = auth_client.patch(f"/api/users/{uid}", json={"is_admin": True})
        assert r.status_code == 200

    def test_update_user_reset_password(self, auth_client):
        uid = self._create_user(auth_client)
        r = auth_client.patch(f"/api/users/{uid}", json={"new_password": "newpassword456"})
        assert r.status_code == 200

    def test_update_user_password_too_short(self, auth_client):
        uid = self._create_user(auth_client)
        r = auth_client.patch(f"/api/users/{uid}", json={"new_password": "short"})
        assert r.status_code == 400

    def test_update_user_not_found(self, auth_client):
        r = auth_client.patch("/api/users/99999", json={"is_admin": False})
        assert r.status_code == 404

    def test_update_no_fields(self, auth_client):
        uid = self._create_user(auth_client)
        r = auth_client.patch(f"/api/users/{uid}", json={})
        assert r.status_code == 200


class TestDeleteUser:
    def test_delete_user(self, auth_client):
        r = auth_client.post("/api/users", json={"username": "alice", "password": "password123"})
        uid = r.json()["id"]
        r2 = auth_client.delete(f"/api/users/{uid}")
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    def test_cannot_delete_self(self, auth_client):
        r = auth_client.get("/api/users")
        admin_id = r.json()[0]["id"]
        r2 = auth_client.delete(f"/api/users/{admin_id}")
        assert r2.status_code == 400

    def test_delete_user_non_admin_forbidden(self, auth_client, api_app):
        auth_client.post("/api/users", json={"username": "regular", "password": "password123"})
        r = auth_client.post("/api/users", json={"username": "victim", "password": "password123"})
        victim_id = r.json()["id"]
        from fastapi.testclient import TestClient

        with TestClient(api_app, base_url="https://testserver") as c:
            c.post("/api/auth/login", json={"username": "regular", "password": "password123"})
            r2 = c.delete(f"/api/users/{victim_id}")
            assert r2.status_code == 403
