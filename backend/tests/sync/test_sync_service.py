"""Tests for backend.sync.service (status composition, sync lock, .eml import)."""

import itertools
from datetime import UTC, datetime
from unittest.mock import patch

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


class TestGetStatus:
    def test_idle_default_when_no_record(self, test_db):
        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)

        status = service.get_status(user_id)
        assert status.status == "idle"
        assert status.last_synced_at is None
        assert status.emails_processed is None
        assert status.sync_interval_minutes == 10

    def test_reflects_stored_record(self, test_db):
        import sqlite3

        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO email_sync_state (user_id, status, emails_processed, emails_total) VALUES (?, 'running', 3, 10)",
            (user_id,),
        )
        conn.commit()
        conn.close()

        status = service.get_status(user_id)
        assert status.status == "running"
        assert status.emails_processed == 3
        assert status.emails_total == 10


class TestSyncLock:
    def test_second_acquire_fails_until_released(self, test_db):
        from backend.sync.service import SyncService

        service = SyncService()
        assert service.try_acquire_lock() is True
        assert service.try_acquire_lock() is False
        service._lock.release()
        assert service.try_acquire_lock() is True
        service._lock.release()

    def test_run_sync_for_user_releases_lock(self, test_db):
        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)
        service.try_acquire_lock()

        with patch("backend.sync.pipeline.run_email_sync_for_user") as mock_run:
            service.run_sync_for_user(user_id)

        mock_run.assert_called_once()
        # Lock was released — acquiring again should succeed
        assert service.try_acquire_lock() is True
        service._lock.release()

    def test_run_sync_for_user_releases_lock_even_on_error(self, test_db):
        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)
        service.try_acquire_lock()

        with patch(
            "backend.sync.pipeline.run_email_sync_for_user", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError):
                service.run_sync_for_user(user_id)

        assert service.try_acquire_lock() is True
        service._lock.release()

    def test_run_sync_for_user_noop_when_no_credentials_row(self, test_db):
        from backend.sync.service import SyncService

        service = SyncService()
        service.try_acquire_lock()
        with patch("backend.sync.pipeline.run_email_sync_for_user") as mock_run:
            service.run_sync_for_user(99999)  # unknown user id
        mock_run.assert_not_called()


class TestResetLastSynced:
    def test_delegates_to_repository(self, test_db):
        import sqlite3

        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO email_sync_state (user_id, status, last_synced_at) VALUES (?, 'idle', ?)",
            (user_id, datetime.now(UTC).isoformat()),
        )
        conn.commit()
        conn.close()

        service.reset_last_synced(user_id)
        assert service.get_status(user_id).last_synced_at is None


class TestTriggerRegroup:
    def test_calls_regroup_all_flights(self, test_db):
        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)
        with patch("backend.sync.grouping.regroup_all_flights") as mock_regroup:
            service.trigger_regroup(user_id)
        mock_regroup.assert_called_once_with(user_id=user_id)


class TestImportEmlFiles:
    _MINIMAL_EML = (
        b"From: airline@example.com\r\n"
        b"Subject: Your booking\r\n"
        b"Date: Mon, 1 Jun 2026 10:00:00 +0000\r\n"
        b"Message-ID: <test123@example.com>\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"No flight info here.\r\n"
    )

    def test_parses_and_imports_valid_eml(self, test_db):
        """A well-formed email with no extractable flight data is parsed without
        error, but doesn't count towards emails_processed (that only increments
        when flight/BCBP data is actually found)."""
        from backend.sync.service import SyncService

        service = SyncService()
        user_id = _seed_user(test_db)

        result = service.import_eml_files([("booking.eml", self._MINIMAL_EML)], user_id)
        assert result["emails_processed"] == 0
        assert result["flights_created"] == 0

    def test_raises_parse_error_on_bad_email(self, test_db):
        from backend.sync.service import EmlParseError, SyncService

        service = SyncService()
        user_id = _seed_user(test_db)

        with patch("email.message_from_bytes", side_effect=ValueError("boom")):
            with pytest.raises(EmlParseError) as exc_info:
                service.import_eml_files([("bad.eml", b"garbage")], user_id)
        assert "bad.eml" in str(exc_info.value)
