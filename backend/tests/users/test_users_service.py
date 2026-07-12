"""Tests for backend.users.service (validation + audit logging)."""

import itertools
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
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
    return user_id


class TestCreateUser:
    def test_rejects_short_username(self, test_db):
        from backend.users.service import UserService, ValidationError

        service = UserService()
        admin_id = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.create_user(admin_id, "abc", "password123", False, None)

    def test_rejects_short_password(self, test_db):
        from backend.users.service import UserService, ValidationError

        service = UserService()
        admin_id = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.create_user(admin_id, "alice", "short", False, None)

    def test_normalizes_username(self, test_db):
        from backend.users.service import UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        created = service.create_user(admin_id, "  Alice  ", "password123", False, None)
        assert created.username == "alice"

    def test_duplicate_username_rejected(self, test_db):
        from backend.users.service import UserService, ValidationError

        service = UserService()
        admin_id = _seed_user(test_db)
        service.create_user(admin_id, "alice", "password123", False, None)
        with pytest.raises(ValidationError):
            service.create_user(admin_id, "alice", "password456", False, None)

    def test_returns_created_user(self, test_db):
        from backend.users.service import UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        created = service.create_user(admin_id, "alice", "password123", True, "alice@example.com")
        assert created.is_admin is True
        assert created.smtp_recipient_address == "alice@example.com"


class TestUpdateUser:
    def test_raises_when_not_found(self, test_db):
        from backend.users.service import UserNotFoundError, UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        with pytest.raises(UserNotFoundError):
            service.update_user(admin_id, 99999, None, None, None)

    def test_rejects_short_new_password(self, test_db):
        from backend.users.service import UserService, ValidationError

        service = UserService()
        admin_id = _seed_user(test_db)
        target_id = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.update_user(admin_id, target_id, None, None, "short")

    def test_promotes_to_admin(self, test_db):
        from backend.users.service import UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        target_id = _seed_user(test_db)
        service.update_user(admin_id, target_id, True, None, None)

        [user] = [u for u in service.list_users() if u.id == target_id]
        assert user.is_admin is True

    def test_no_fields_is_noop(self, test_db):
        from backend.users.service import UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        target_id = _seed_user(test_db)
        service.update_user(admin_id, target_id, None, None, None)  # should not raise


class TestDeleteUser:
    def test_raises_when_deleting_self(self, test_db):
        from backend.users.service import SelfDeleteError, UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        with pytest.raises(SelfDeleteError):
            service.delete_user(admin_id, admin_id)

    def test_deletes_other_user(self, test_db):
        from backend.users.service import UserService

        service = UserService()
        admin_id = _seed_user(test_db)
        target_id = _seed_user(test_db)
        service.delete_user(admin_id, target_id)

        assert not any(u.id == target_id for u in service.list_users())
