"""Tests for the trip-sharing / invitations / trusted-users API routes
(sharing_routes.py): /api/trips/{id}/share, /api/trips/invitations,
/api/trips/{id}/shares, /api/trips/{id}/leave, /api/settings/trusted-users."""


def _make_trip(client, name="Iceland Trip"):
    r = client.post("/api/trips", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_second_user_client(api_app, admin_client, username="user2"):
    """Create a second (non-admin) user and return a logged-in TestClient for them."""
    from fastapi.testclient import TestClient

    admin_client.post(
        "/api/users",
        json={"username": username, "password": "password123", "is_admin": False},
    )
    c2 = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
    c2.post("/api/auth/login", json={"username": username, "password": "password123"})
    return c2


class TestShareTrip:
    def test_share_trip_success(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)

        r = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "pending"

        [invitation] = other.get("/api/trips/invitations").json()
        assert invitation["trip_id"] == trip_id

    def test_share_trip_not_owner_returns_404(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client, username="user2")
        third = _make_second_user_client(api_app, auth_client, username="user3")
        trip_id = _make_trip(auth_client)

        r = other.post(f"/api/trips/{trip_id}/share", json={"username": "user3"})
        assert r.status_code == 404
        assert third is not None

    def test_inviting_by_a_differently_cased_username_finds_the_account(self, auth_client, api_app):
        """Usernames are stored lowercased, and this path handed the typed
        spelling straight to the lookup — so inviting "User2" reported that no
        such account existed. Normalising inside `find_by_username` covers this
        caller and the trusted-user one below without either having to remember."""
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)

        r = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "User2"})
        assert r.status_code == 201, r.text
        assert [i["trip_id"] for i in other.get("/api/trips/invitations").json()] == [trip_id]

    def test_share_trip_invitee_not_found_returns_404(self, auth_client):
        trip_id = _make_trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "nonexistent"})
        assert r.status_code == 404

    def test_share_trip_with_self_returns_400(self, auth_client):
        trip_id = _make_trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "admin"})
        assert r.status_code == 400

    def test_share_trip_already_shared_returns_400(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)

        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        [invitation] = other.get("/api/trips/invitations").json()
        accept_resp = other.post(f"/api/trips/invitations/{invitation['id']}/accept")
        assert accept_resp.status_code == 200

        r = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        assert r.status_code == 400

    def test_share_trip_unauthenticated_returns_401(self, client):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        client.cookies.clear()
        r = client.post("/api/trips/nonexistent/share", json={"username": "user2"})
        assert r.status_code == 401

    def test_trusted_invitee_auto_accepted(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        other.post("/api/settings/trusted-users", json={"username": "admin"})
        trip_id = _make_trip(auth_client)

        r = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        assert r.status_code == 201
        assert r.json()["status"] == "accepted"


class TestInvitations:
    def test_list_invitations_empty(self, auth_client):
        r = auth_client.get("/api/trips/invitations")
        assert r.status_code == 200
        assert r.json() == []

    def test_accept_invitation(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        [invitation] = other.get("/api/trips/invitations").json()

        r = other.post(f"/api/trips/invitations/{invitation['id']}/accept")
        assert r.status_code == 200
        assert other.get("/api/trips/invitations").json() == []

    def test_accept_invitation_not_found_returns_404(self, auth_client):
        r = auth_client.post("/api/trips/invitations/99999/accept")
        assert r.status_code == 404

    def test_reject_invitation(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        [invitation] = other.get("/api/trips/invitations").json()

        r = other.post(f"/api/trips/invitations/{invitation['id']}/reject")
        assert r.status_code == 200
        assert other.get("/api/trips/invitations").json() == []

    def test_reject_invitation_not_found_returns_404(self, auth_client):
        r = auth_client.post("/api/trips/invitations/99999/reject")
        assert r.status_code == 404


class TestListAndRevokeShares:
    def test_list_trip_shares(self, auth_client, api_app):
        _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})

        r = auth_client.get(f"/api/trips/{trip_id}/shares")
        assert r.status_code == 200
        [share] = r.json()
        assert share["username"] == "user2"
        assert share["status"] == "pending"

    def test_list_trip_shares_not_owner_returns_404(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)

        r = other.get(f"/api/trips/{trip_id}/shares")
        assert r.status_code == 404

    def test_revoke_trip_share(self, auth_client, api_app):
        _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        [share] = auth_client.get(f"/api/trips/{trip_id}/shares").json()

        r = auth_client.delete(f"/api/trips/{trip_id}/shares/{share['user_id']}")
        assert r.status_code == 204
        assert auth_client.get(f"/api/trips/{trip_id}/shares").json() == []

    def test_revoke_trip_share_not_owner_returns_404(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        [share] = auth_client.get(f"/api/trips/{trip_id}/shares").json()

        r = other.delete(f"/api/trips/{trip_id}/shares/{share['user_id']}")
        assert r.status_code == 404


class TestLeaveTrip:
    def test_leave_trip(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "user2"})
        [invitation] = other.get("/api/trips/invitations").json()
        other.post(f"/api/trips/invitations/{invitation['id']}/accept")

        r = other.delete(f"/api/trips/{trip_id}/leave")
        assert r.status_code == 204
        assert auth_client.get(f"/api/trips/{trip_id}/shares").json() == []

    def test_leave_trip_no_active_share_returns_404(self, auth_client, api_app):
        other = _make_second_user_client(api_app, auth_client)
        trip_id = _make_trip(auth_client)

        r = other.delete(f"/api/trips/{trip_id}/leave")
        assert r.status_code == 404


class TestTrustedUsers:
    def test_list_trusted_users_empty(self, auth_client):
        r = auth_client.get("/api/settings/trusted-users")
        assert r.status_code == 200
        assert r.json() == []

    def test_add_and_list_trusted_user(self, auth_client, api_app):
        _make_second_user_client(api_app, auth_client)

        r = auth_client.post("/api/settings/trusted-users", json={"username": "user2"})
        assert r.status_code == 201

        [trusted] = auth_client.get("/api/settings/trusted-users").json()
        assert trusted["username"] == "user2"

    def test_trusting_by_a_differently_cased_username_finds_the_account(self, auth_client, api_app):
        _make_second_user_client(api_app, auth_client)

        r = auth_client.post("/api/settings/trusted-users", json={"username": "USER2"})
        assert r.status_code == 201
        [trusted] = auth_client.get("/api/settings/trusted-users").json()
        assert trusted["username"] == "user2"

    def test_add_trusted_user_not_found_returns_404(self, auth_client):
        r = auth_client.post("/api/settings/trusted-users", json={"username": "nonexistent"})
        assert r.status_code == 404

    def test_add_trusted_user_self_returns_400(self, auth_client):
        r = auth_client.post("/api/settings/trusted-users", json={"username": "admin"})
        assert r.status_code == 400

    def test_remove_trusted_user(self, auth_client, api_app):
        _make_second_user_client(api_app, auth_client)
        auth_client.post("/api/settings/trusted-users", json={"username": "user2"})
        [trusted] = auth_client.get("/api/settings/trusted-users").json()

        r = auth_client.delete(f"/api/settings/trusted-users/{trusted['user_id']}")
        assert r.status_code == 204
        assert auth_client.get("/api/settings/trusted-users").json() == []
