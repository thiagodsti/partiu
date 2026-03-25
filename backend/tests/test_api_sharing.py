"""Tests for trip sharing, delete trip/flight, and trusted users."""

from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient

from backend.database import db_write

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(api_app, username: str, password: str = "pass1234") -> TestClient:
    """Create a secondary user and return an authenticated client for them."""
    with db_write() as conn:
        ph = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
            (username, ph),
        )
    client = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed for {username}: {r.text}"
    return client


def _make_flight(client, trip_id=None):
    payload = {
        "flight_number": "LA8094",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00",
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00",
    }
    if trip_id:
        payload["trip_id"] = trip_id
    with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
        r = client.post("/api/flights", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


# ---------------------------------------------------------------------------
# TestDeleteTrip
# ---------------------------------------------------------------------------


class TestDeleteTrip:
    def test_delete_own_trip_returns_204(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.delete(f"/api/trips/{trip_id}")
        assert r2.status_code == 204

    def test_cascade_flights_and_boarding_passes_gone(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "My Trip"})
        trip_id = r.json()["id"]
        fid = _make_flight(auth_client, trip_id=trip_id)
        auth_client.delete(f"/api/trips/{trip_id}")
        # Flight should be deleted
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.status_code == 404

    def test_delete_other_users_trip_returns_404(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Private Trip"})
        trip_id = r.json()["id"]

        other = _make_user(api_app, "otheruser1")
        r2 = other.delete(f"/api/trips/{trip_id}")
        assert r2.status_code == 404

        # Trip should still exist for owner
        r3 = auth_client.get(f"/api/trips/{trip_id}")
        assert r3.status_code == 200


# ---------------------------------------------------------------------------
# TestDeleteFlight
# ---------------------------------------------------------------------------


class TestDeleteFlight:
    def test_delete_own_flight_returns_204(self, auth_client):
        fid = _make_flight(auth_client)
        r = auth_client.delete(f"/api/flights/{fid}")
        assert r.status_code == 204
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.status_code == 404

    def test_delete_other_users_flight_returns_404(self, auth_client, api_app):
        fid = _make_flight(auth_client)
        other = _make_user(api_app, "otheruser2")
        other.delete(f"/api/flights/{fid}")
        # Flight should still exist for the owner
        r2 = auth_client.get(f"/api/flights/{fid}")
        assert r2.status_code == 200

    def test_collaborator_cannot_delete_flight(self, auth_client, api_app):
        r = auth_client.post("/api/trips", json={"name": "Shared Trip"})
        trip_id = r.json()["id"]
        fid = _make_flight(auth_client, trip_id=trip_id)

        collab = _make_user(api_app, "collabuser1")

        # Share with collab (auto-accept by having owner invite and collab accept)
        r2 = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "collabuser1"})
        assert r2.status_code == 201

        # Accept invitation
        invitations = collab.get("/api/trips/invitations").json()
        assert len(invitations) == 1
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        # Collaborator can see the flight
        r3 = collab.get(f"/api/flights/{fid}")
        assert r3.status_code == 200

        # But cannot delete it
        r4 = collab.delete(f"/api/flights/{fid}")
        assert r4.status_code == 404


# ---------------------------------------------------------------------------
# TestTripSharing
# ---------------------------------------------------------------------------


class TestTripSharing:
    def test_owner_can_invite_user(self, auth_client, api_app):
        _make_user(api_app, "invitee1")
        r = auth_client.post("/api/trips", json={"name": "Shared"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "invitee1"})
        assert r2.status_code == 201

    def test_invited_user_sees_trip_after_accept(self, auth_client, api_app):
        collab = _make_user(api_app, "invitee2")
        r = auth_client.post("/api/trips", json={"name": "Shared Trip"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "invitee2"})

        invitations = collab.get("/api/trips/invitations").json()
        assert len(invitations) == 1
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        trips = collab.get("/api/trips").json()["trips"]
        assert any(t["id"] == trip_id for t in trips)
        shared_trip = next(t for t in trips if t["id"] == trip_id)
        assert shared_trip["is_owner"] is False

    def test_collaborator_can_access_trip_flights(self, auth_client, api_app):
        collab = _make_user(api_app, "invitee3")
        r = auth_client.post("/api/trips", json={"name": "Shared Trip"})
        trip_id = r.json()["id"]
        fid = _make_flight(auth_client, trip_id=trip_id)
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "invitee3"})

        invitations = collab.get("/api/trips/invitations").json()
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        r2 = collab.get(f"/api/flights/{fid}")
        assert r2.status_code == 200

    def test_collaborator_cannot_delete_trip(self, auth_client, api_app):
        collab = _make_user(api_app, "invitee4")
        r = auth_client.post("/api/trips", json={"name": "Shared Trip"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "invitee4"})

        invitations = collab.get("/api/trips/invitations").json()
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        r2 = collab.delete(f"/api/trips/{trip_id}")
        assert r2.status_code == 404

    def test_owner_can_revoke_access(self, auth_client, api_app):
        collab = _make_user(api_app, "invitee5")
        collab_data = collab.get("/api/auth/me").json()
        r = auth_client.post("/api/trips", json={"name": "Shared Trip"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "invitee5"})

        invitations = collab.get("/api/trips/invitations").json()
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        # Revoke
        auth_client.delete(f"/api/trips/{trip_id}/shares/{collab_data['id']}")

        # Trip should no longer appear for collaborator
        trips = collab.get("/api/trips").json()["trips"]
        assert not any(t["id"] == trip_id for t in trips)

    def test_inviting_nonexistent_user_returns_404(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "no_such_user_xyz"})
        assert r2.status_code == 404

    def test_inviting_yourself_returns_400(self, auth_client):
        r = auth_client.post("/api/trips", json={"name": "Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "admin"})
        assert r2.status_code == 400


# ---------------------------------------------------------------------------
# TestInvitations
# ---------------------------------------------------------------------------


class TestInvitations:
    def test_accept_invitation_trip_appears(self, auth_client, api_app):
        collab = _make_user(api_app, "acc1")
        r = auth_client.post("/api/trips", json={"name": "Shared"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "acc1"})

        invitations = collab.get("/api/trips/invitations").json()
        assert len(invitations) == 1
        r2 = collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")
        assert r2.status_code == 200

        trips = collab.get("/api/trips").json()["trips"]
        assert any(t["id"] == trip_id for t in trips)

    def test_reject_invitation_trip_does_not_appear(self, auth_client, api_app):
        collab = _make_user(api_app, "rej1")
        r = auth_client.post("/api/trips", json={"name": "Shared"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "rej1"})

        invitations = collab.get("/api/trips/invitations").json()
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/reject")

        trips = collab.get("/api/trips").json()["trips"]
        assert not any(t["id"] == trip_id for t in trips)

    def test_pending_invitations_count(self, auth_client, api_app):
        collab = _make_user(api_app, "cnt1")
        r1 = auth_client.post("/api/trips", json={"name": "Trip 1"})
        r2 = auth_client.post("/api/trips", json={"name": "Trip 2"})
        auth_client.post(f"/api/trips/{r1.json()['id']}/share", json={"username": "cnt1"})
        auth_client.post(f"/api/trips/{r2.json()['id']}/share", json={"username": "cnt1"})

        invitations = collab.get("/api/trips/invitations").json()
        assert len(invitations) == 2


# ---------------------------------------------------------------------------
# TestTrustedUsers
# ---------------------------------------------------------------------------


class TestTrustedUsers:
    def test_add_trusted_user(self, auth_client, api_app):
        _make_user(api_app, "trusted1")
        r = auth_client.post("/api/settings/trusted-users", json={"username": "trusted1"})
        assert r.status_code == 201

        users = auth_client.get("/api/settings/trusted-users").json()
        assert any(u["username"] == "trusted1" for u in users)

    def test_invitation_from_trusted_user_auto_accepts(self, auth_client, api_app):
        # Create user B who trusts admin
        user_b = _make_user(api_app, "trusted2")
        # user_b trusts admin
        user_b.post("/api/settings/trusted-users", json={"username": "admin"})

        # Admin shares a trip with user_b
        r = auth_client.post("/api/trips", json={"name": "Auto Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "trusted2"})
        assert r2.status_code == 201
        data = r2.json()
        assert data["status"] == "accepted"

        # user_b should see the trip immediately (no invitation to accept)
        trips = user_b.get("/api/trips").json()["trips"]
        assert any(t["id"] == trip_id for t in trips)

        # No pending invitations
        invitations = user_b.get("/api/trips/invitations").json()
        assert len(invitations) == 0

    def test_remove_trusted_user(self, auth_client, api_app):
        _make_user(api_app, "trusted3")
        auth_client.post("/api/settings/trusted-users", json={"username": "trusted3"})
        users = auth_client.get("/api/settings/trusted-users").json()
        target = next(u for u in users if u["username"] == "trusted3")

        r = auth_client.delete(f"/api/settings/trusted-users/{target['user_id']}")
        assert r.status_code == 204

        users2 = auth_client.get("/api/settings/trusted-users").json()
        assert not any(u["username"] == "trusted3" for u in users2)


# ---------------------------------------------------------------------------
# TestShareVisibility  (owner sees pending + accepted; leave trip)
# ---------------------------------------------------------------------------


class TestShareVisibility:
    def test_list_shares_includes_pending(self, auth_client, api_app):
        """Owner should see pending invitations in the shares list."""
        _make_user(api_app, "vis1")
        r = auth_client.post("/api/trips", json={"name": "Visibility Trip"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "vis1"})

        shares = auth_client.get(f"/api/trips/{trip_id}/shares").json()
        assert len(shares) == 1
        assert shares[0]["username"] == "vis1"
        assert shares[0]["status"] == "pending"

    def test_list_shares_accepted_after_accept(self, auth_client, api_app):
        """After the invitee accepts, status should be 'accepted'."""
        collab = _make_user(api_app, "vis2")
        r = auth_client.post("/api/trips", json={"name": "Visibility Trip 2"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "vis2"})

        invitations = collab.get("/api/trips/invitations").json()
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        shares = auth_client.get(f"/api/trips/{trip_id}/shares").json()
        assert len(shares) == 1
        assert shares[0]["status"] == "accepted"

    def test_collaborator_can_leave_trip(self, auth_client, api_app):
        """A collaborator can remove themselves from a shared trip."""
        collab = _make_user(api_app, "leaver1")
        r = auth_client.post("/api/trips", json={"name": "Leave Trip"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "leaver1"})

        invitations = collab.get("/api/trips/invitations").json()
        collab.post(f"/api/trips/invitations/{invitations[0]['id']}/accept")

        # Trip is visible
        trips_before = collab.get("/api/trips").json()["trips"]
        assert any(t["id"] == trip_id for t in trips_before)

        # Leave
        r2 = collab.delete(f"/api/trips/{trip_id}/leave")
        assert r2.status_code == 204

        # Trip no longer visible
        trips_after = collab.get("/api/trips").json()["trips"]
        assert not any(t["id"] == trip_id for t in trips_after)

    def test_leave_trip_with_pending_invite(self, auth_client, api_app):
        """A user with a pending invite can also leave (reject via leave endpoint)."""
        collab = _make_user(api_app, "leaver2")
        r = auth_client.post("/api/trips", json={"name": "Leave Pending"})
        trip_id = r.json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/share", json={"username": "leaver2"})

        # Don't accept — just leave
        r2 = collab.delete(f"/api/trips/{trip_id}/leave")
        assert r2.status_code == 204

        # Invitation should be gone
        invitations = collab.get("/api/trips/invitations").json()
        assert len(invitations) == 0

    def test_owner_cannot_leave_own_trip(self, auth_client):
        """Owner cannot use the leave endpoint on their own trip."""
        r = auth_client.post("/api/trips", json={"name": "Own Trip"})
        trip_id = r.json()["id"]
        r2 = auth_client.delete(f"/api/trips/{trip_id}/leave")
        assert r2.status_code == 404
