"""Tests for backend.trips.sharing_service (ownership checks + sharing/trust business rules)."""

import itertools
import uuid
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> tuple[int, str]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id, username


def _seed_trip(db_path: str, user_id: int, name: str = "Test Trip") -> str:
    import sqlite3

    trip_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO trips (id, user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (trip_id, user_id, name, now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


def _share_status(service, trip_id: str, invitee_id: int) -> str:
    share = service._repository.get_share(trip_id, invitee_id)
    assert share is not None
    return share.status


class TestShareTrip:
    def test_raises_when_not_owner(self, test_db):
        from backend.trips.sharing_service import ShareService, TripAccessError

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        other_id, _ = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.share_trip(trip_id, other_id, "other", invitee_username)

    def test_raises_when_invitee_not_found(self, test_db):
        from backend.trips.sharing_service import ShareService, UserNotFoundError

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(UserNotFoundError):
            service.share_trip(trip_id, owner_id, owner_username, "nonexistent")

    def test_raises_when_sharing_with_self(self, test_db):
        from backend.trips.sharing_service import SelfShareError, ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(SelfShareError):
            service.share_trip(trip_id, owner_id, owner_username, owner_username)

    def test_pending_by_default(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        result = service.share_trip(trip_id, owner_id, owner_username, invitee_username)
        assert result == {"ok": True, "status": "pending"}

    def test_auto_accepts_when_invitee_trusts_inviter(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service._repository.add_trusted_user(invitee_id, owner_id)

        result = service.share_trip(trip_id, owner_id, owner_username, invitee_username)
        assert result == {"ok": True, "status": "accepted"}

    def test_raises_when_already_accepted(self, test_db):
        from backend.trips.sharing_service import AlreadySharedError, ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service._repository.create_share(trip_id, invitee_id, owner_id, "accepted")

        with pytest.raises(AlreadySharedError):
            service.share_trip(trip_id, owner_id, owner_username, invitee_username)

    def test_reinvite_resets_rejected_to_pending(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service._repository.create_share(trip_id, invitee_id, owner_id, "rejected")

        result = service.share_trip(trip_id, owner_id, owner_username, invitee_username)
        assert result == {"ok": True}
        assert _share_status(service, trip_id, invitee_id) == "pending"


class TestInvitations:
    def test_accept_raises_when_not_found(self, test_db):
        from backend.trips.sharing_service import InvitationNotFoundError, ShareService

        service = ShareService()
        user_id, _ = _seed_user(test_db)
        with pytest.raises(InvitationNotFoundError):
            service.accept_invitation(99999, user_id)

    def test_accept_marks_share_accepted(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service.share_trip(trip_id, owner_id, owner_username, invitee_username)
        [invitation] = service.list_invitations(invitee_id)

        service.accept_invitation(invitation.id, invitee_id)
        assert _share_status(service, trip_id, invitee_id) == "accepted"

    def test_reject_marks_share_rejected(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, invitee_username = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service.share_trip(trip_id, owner_id, owner_username, invitee_username)
        [invitation] = service.list_invitations(invitee_id)

        service.reject_invitation(invitation.id, invitee_id)
        assert _share_status(service, trip_id, invitee_id) == "rejected"


class TestTripShares:
    def test_list_raises_when_not_owner(self, test_db):
        from backend.trips.sharing_service import ShareService, TripAccessError

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        other_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_trip_shares(trip_id, other_id)

    def test_revoke_raises_when_not_owner(self, test_db):
        from backend.trips.sharing_service import ShareService, TripAccessError

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        other_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.revoke_trip_share(trip_id, invitee_id, other_id)

    def test_revoke_removes_share(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service._repository.create_share(trip_id, invitee_id, owner_id, "accepted")

        service.revoke_trip_share(trip_id, invitee_id, owner_id)
        assert service._repository.get_share(trip_id, invitee_id) is None


class TestLeaveTrip:
    def test_raises_when_no_active_share(self, test_db):
        from backend.trips.sharing_service import SharedTripNotFoundError, ShareService

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        other_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(SharedTripNotFoundError):
            service.leave_trip(trip_id, other_id)

    def test_removes_own_share(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        service._repository.create_share(trip_id, invitee_id, owner_id, "accepted")

        service.leave_trip(trip_id, invitee_id)
        assert service._repository.get_share(trip_id, invitee_id) is None


class TestTrustedUsers:
    def test_raises_when_target_not_found(self, test_db):
        from backend.trips.sharing_service import ShareService, UserNotFoundError

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        with pytest.raises(UserNotFoundError):
            service.add_trusted_user(owner_id, "nonexistent")

    def test_raises_when_trusting_self(self, test_db):
        from backend.trips.sharing_service import SelfTrustError, ShareService

        service = ShareService()
        owner_id, owner_username = _seed_user(test_db)
        with pytest.raises(SelfTrustError):
            service.add_trusted_user(owner_id, owner_username)

    def test_adds_trusted_user(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        trusted_id, trusted_username = _seed_user(test_db)

        service.add_trusted_user(owner_id, trusted_username)
        trusted = service.list_trusted_users(owner_id)
        assert len(trusted) == 1
        assert trusted[0].user_id == trusted_id

    def test_removes_trusted_user(self, test_db):
        from backend.trips.sharing_service import ShareService

        service = ShareService()
        owner_id, _ = _seed_user(test_db)
        trusted_id, trusted_username = _seed_user(test_db)
        service.add_trusted_user(owner_id, trusted_username)

        service.remove_trusted_user(owner_id, trusted_id)
        assert service.list_trusted_users(owner_id) == []
