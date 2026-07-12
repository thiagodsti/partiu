"""Tests for backend.trips.sharing_repository (raw CRUD for trip_shares and trusted_users)."""

import itertools
import uuid
from datetime import UTC, datetime

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


class TestShareLifecycle:
    def test_create_share_and_get(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        repo.create_share(trip_id, invitee_id, owner_id, "pending")
        share = repo.get_share(trip_id, invitee_id)
        assert share is not None
        assert share.status == "pending"

    def test_get_share_returns_none_when_absent(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        assert repo.get_share(trip_id, invitee_id) is None

    def test_reinvite_resets_to_pending(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create_share(trip_id, invitee_id, owner_id, "rejected")
        share = repo.get_share(trip_id, invitee_id)
        assert share is not None

        repo.reinvite(share.id, owner_id)
        reinvited = repo.get_share(trip_id, invitee_id)
        assert reinvited is not None
        assert reinvited.status == "pending"

    def test_invitee_trusts_inviter(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        assert repo.invitee_trusts_inviter(invitee_id, owner_id) is False

        repo.add_trusted_user(invitee_id, owner_id)
        assert repo.invitee_trusts_inviter(invitee_id, owner_id) is True

    def test_list_invitations_for_user(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, owner_username = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id, name="Invite Trip")
        repo.create_share(trip_id, invitee_id, owner_id, "pending")

        [invitation] = repo.list_invitations_for_user(invitee_id)
        assert invitation.trip_id == trip_id
        assert invitation.trip_name == "Invite Trip"
        assert invitation.invited_by_username == owner_username

    def test_list_invitations_excludes_non_pending(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create_share(trip_id, invitee_id, owner_id, "accepted")

        assert repo.list_invitations_for_user(invitee_id) == []

    def test_find_pending_invitation(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create_share(trip_id, invitee_id, owner_id, "pending")
        share = repo.get_share(trip_id, invitee_id)
        assert share is not None

        assert repo.find_pending_invitation(share.id, invitee_id) == share.id
        assert repo.find_pending_invitation(share.id, owner_id) is None

    def test_update_invitation_status(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create_share(trip_id, invitee_id, owner_id, "pending")
        share = repo.get_share(trip_id, invitee_id)
        assert share is not None

        repo.update_invitation_status(share.id, "accepted")
        updated = repo.get_share(trip_id, invitee_id)
        assert updated is not None
        assert updated.status == "accepted"

    def test_list_shares_for_trip_includes_pending_and_accepted(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        pending_id, _ = _seed_user(test_db)
        accepted_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create_share(trip_id, pending_id, owner_id, "pending")
        repo.create_share(trip_id, accepted_id, owner_id, "accepted")

        shares = repo.list_shares_for_trip(trip_id)
        assert {s.status for s in shares} == {"pending", "accepted"}

    def test_delete_share(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        repo.create_share(trip_id, invitee_id, owner_id, "accepted")

        repo.delete_share(trip_id, invitee_id)
        assert repo.get_share(trip_id, invitee_id) is None

    def test_find_active_share(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        invitee_id, _ = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        assert repo.find_active_share(trip_id, invitee_id) is False

        repo.create_share(trip_id, invitee_id, owner_id, "pending")
        assert repo.find_active_share(trip_id, invitee_id) is True


class TestTrustedUsers:
    def test_add_and_list_trusted_user(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        trusted_id, trusted_username = _seed_user(test_db)

        repo.add_trusted_user(owner_id, trusted_id)
        trusted = repo.list_trusted_users(owner_id)
        assert len(trusted) == 1
        assert trusted[0].username == trusted_username

    def test_add_trusted_user_is_idempotent(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        trusted_id, _ = _seed_user(test_db)

        repo.add_trusted_user(owner_id, trusted_id)
        repo.add_trusted_user(owner_id, trusted_id)  # should not raise
        assert len(repo.list_trusted_users(owner_id)) == 1

    def test_remove_trusted_user(self, test_db):
        from backend.trips.sharing_repository import ShareRepository

        repo = ShareRepository()
        owner_id, _ = _seed_user(test_db)
        trusted_id, _ = _seed_user(test_db)
        repo.add_trusted_user(owner_id, trusted_id)

        repo.remove_trusted_user(owner_id, trusted_id)
        assert repo.list_trusted_users(owner_id) == []
