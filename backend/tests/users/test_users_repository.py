"""Tests for backend.users.repository (raw CRUD for the users table)."""

import itertools
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
    return _seed_user_with_username(db_path)[0]


def _seed_user_with_username(db_path: str) -> tuple[int, str]:
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


class TestListUsers:
    def test_returns_seeded_users_ordered_by_id(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        id1 = _seed_user(test_db)
        id2 = _seed_user(test_db)

        users = repo.list_users()
        ids = [u.id for u in users]
        assert ids.index(id1) < ids.index(id2)


class TestExists:
    def test_true_for_existing(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        user_id = _seed_user(test_db)
        assert repo.exists(user_id) is True

    def test_false_for_nonexistent(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        assert repo.exists(99999) is False


class TestCreateUser:
    def test_returns_new_id(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        user_id = repo.create_user("alice", "hashed-pw", False, None)
        assert repo.exists(user_id) is True

    def test_duplicate_username_raises(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        repo.create_user("alice", "hashed-pw", False, None)
        with pytest.raises(Exception):
            repo.create_user("alice", "other-hash", False, None)


class TestUpdateUser:
    def test_updates_given_columns(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        user_id = _seed_user(test_db)
        repo.update_user(user_id, {"is_admin": 1, "smtp_recipient_address": "a@b.com"})

        [user] = [u for u in repo.list_users() if u.id == user_id]
        assert user.is_admin is True
        assert user.smtp_recipient_address == "a@b.com"


class TestDeleteUser:
    def test_removes_user(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        user_id = _seed_user(test_db)
        repo.delete_user(user_id)
        assert repo.exists(user_id) is False


class TestListCredentialColumns:
    def test_includes_every_user(self, test_db):
        import sqlite3

        from backend.users.repository import UserRepository

        repo = UserRepository()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "UPDATE users SET gmail_app_password = ?, immich_api_key = ? WHERE id = ?",
            ("secret-pw", "secret-key", user_id),
        )
        conn.commit()
        conn.close()

        rows = repo.list_credential_columns()
        [row] = [r for r in rows if r["id"] == user_id]
        assert row["gmail_app_password"] == "secret-pw"
        assert row["immich_api_key"] == "secret-key"

    def test_empty_when_no_users(self, test_db):
        from backend.users.repository import UserRepository

        assert UserRepository().list_credential_columns() == []


class TestFindByUsername:
    def test_finds_existing_user(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        user_id, username = _seed_user_with_username(test_db)

        found = repo.find_by_username(username)
        assert found is not None
        assert found.id == user_id
        assert found.username == username

    def test_returns_none_for_unknown(self, test_db):
        from backend.users.repository import UserRepository

        repo = UserRepository()
        assert repo.find_by_username("nonexistent") is None
