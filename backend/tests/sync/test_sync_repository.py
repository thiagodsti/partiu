"""Tests for backend.sync.repository (email_sync_state rows + user IMAP credentials)."""

import itertools
from datetime import UTC, datetime

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


class TestGetLatestState:
    def test_none_when_no_record(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        assert repo.get_latest_state(user_id) is None

    def test_returns_latest_record(self, test_db):
        import sqlite3

        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO email_sync_state (user_id, status, last_synced_at) VALUES (?, 'idle', ?)",
            (user_id, datetime.now(UTC).isoformat()),
        )
        conn.commit()
        conn.close()

        state = repo.get_latest_state(user_id)
        assert state is not None
        assert state.status == "idle"
        assert state.last_synced_at is not None

    def test_isolates_by_user(self, test_db):
        import sqlite3

        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user1 = _seed_user(test_db)
        user2 = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute("INSERT INTO email_sync_state (user_id, status) VALUES (?, 'idle')", (user1,))
        conn.commit()
        conn.close()

        assert repo.get_latest_state(user1) is not None
        assert repo.get_latest_state(user2) is None


class TestUpsertState:
    def test_creates_row_when_none_exists(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        repo.upsert_state(user_id, status="running")

        state = repo.get_latest_state(user_id)
        assert state is not None
        assert state.status == "running"

    def test_updates_existing_row(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        repo.upsert_state(user_id, status="running")
        repo.upsert_state(user_id, status="idle", last_error="")

        state = repo.get_latest_state(user_id)
        assert state is not None
        assert state.status == "idle"

    def test_rejects_unknown_columns(self, test_db):
        import pytest

        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        with pytest.raises(ValueError):
            repo.upsert_state(user_id, not_a_real_column="x")


class TestProcessedEmails:
    def test_not_processed_returns_false(self, test_db):
        from backend.sync.repository import SyncRepository

        assert SyncRepository().is_email_processed(999, "<never-seen@test.com>") is False

    def test_mark_then_check(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        repo.mark_email_processed(user_id, "<msg1@test.com>")
        assert repo.is_email_processed(user_id, "<msg1@test.com>") is True

    def test_mark_twice_is_idempotent(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        repo.mark_email_processed(user_id, "<dup@test.com>")
        repo.mark_email_processed(user_id, "<dup@test.com>")  # should not raise
        assert repo.is_email_processed(user_id, "<dup@test.com>") is True

    def test_different_users_isolated(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        uid1 = _seed_user(test_db)
        uid2 = _seed_user(test_db)
        repo.mark_email_processed(uid1, "<shared@test.com>")
        assert repo.is_email_processed(uid1, "<shared@test.com>") is True
        assert repo.is_email_processed(uid2, "<shared@test.com>") is False


class TestGetSyncIntervalMinutes:
    def test_defaults_to_ten(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        assert repo.get_sync_interval_minutes() == 10

    def test_reads_configured_value(self, test_db):
        from backend.database import set_global_setting
        from backend.sync.repository import SyncRepository

        set_global_setting("sync_interval_minutes", "30")
        repo = SyncRepository()
        assert repo.get_sync_interval_minutes() == 30


class TestResetLastSynced:
    def test_clears_last_synced_at(self, test_db):
        import sqlite3

        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO email_sync_state (user_id, status, last_synced_at) VALUES (?, 'idle', ?)",
            (user_id, datetime.now(UTC).isoformat()),
        )
        conn.commit()
        conn.close()

        repo.reset_last_synced(user_id)
        state = repo.get_latest_state(user_id)
        assert state is not None
        assert state.last_synced_at is None


class TestGetSyncCredentials:
    def test_returns_credentials_row(self, test_db):
        import sqlite3

        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "UPDATE users SET gmail_address = ?, imap_host = ?, imap_port = ? WHERE id = ?",
            ("me@gmail.com", "imap.gmail.com", 993, user_id),
        )
        conn.commit()
        conn.close()

        creds = repo.get_sync_credentials(user_id)
        assert creds is not None
        assert creds["gmail_address"] == "me@gmail.com"
        assert creds["imap_port"] == 993

    def test_none_for_unknown_user(self, test_db):
        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        assert repo.get_sync_credentials(99999) is None


class TestListAllSyncCredentials:
    def test_empty_when_no_users(self, test_db):
        from backend.sync.repository import SyncRepository

        assert SyncRepository().list_all_sync_credentials() == []

    def test_includes_every_user(self, test_db):
        import sqlite3

        from backend.sync.repository import SyncRepository

        repo = SyncRepository()
        user1 = _seed_user(test_db)
        user2 = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute("UPDATE users SET gmail_address = ? WHERE id = ?", ("me@gmail.com", user1))
        conn.commit()
        conn.close()

        rows = repo.list_all_sync_credentials()
        ids = {r["id"] for r in rows}
        assert {user1, user2} <= ids
        assert next(r["gmail_address"] for r in rows if r["id"] == user1) == "me@gmail.com"
