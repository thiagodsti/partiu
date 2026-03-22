"""Tests for backend.sync_job utility functions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_email_msg(message_id="<test@example.com>", subject="Test", body="", html_body=""):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id=message_id,
        sender="airline@example.com",
        subject=subject,
        body=body,
        date=datetime.now(UTC),
        html_body=html_body,
        pdf_attachments=[],
    )


class TestDtToIso:
    def test_none_returns_none(self):
        from backend.utils import dt_to_iso

        assert dt_to_iso(None) is None

    def test_aware_datetime(self):
        from backend.utils import dt_to_iso

        dt = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result
        assert "+" in result or "Z" in result or "UTC" in result

    def test_naive_datetime_gets_utc(self):
        from backend.utils import dt_to_iso

        dt = datetime(2025, 6, 1, 10, 0, 0)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result

    def test_non_datetime_falls_back_to_str(self):
        from backend.utils import dt_to_iso

        result = dt_to_iso("2025-06-01")
        assert result == "2025-06-01"


class TestSyncState:
    def test_get_sync_state_empty(self, test_db):
        from backend.sync_job import _get_sync_state

        result = _get_sync_state(999)
        assert result == {}

    def test_set_and_get_sync_status(self, test_db):
        from backend.database import db_write
        from backend.sync_job import _get_sync_state, _set_sync_status

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u1', 'h', 1)"
            )
            user_id = cur.lastrowid

        _set_sync_status(user_id, "syncing")
        state = _get_sync_state(user_id)
        assert state["status"] == "syncing"

    def test_set_sync_status_updates_existing(self, test_db):
        from backend.database import db_write
        from backend.sync_job import _get_sync_state, _set_sync_status

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u2', 'h', 1)"
            )
            user_id = cur.lastrowid

        _set_sync_status(user_id, "syncing")
        _set_sync_status(user_id, "idle", error="")
        state = _get_sync_state(user_id)
        assert state["status"] == "idle"

    def test_set_sync_complete(self, test_db):
        from backend.database import db_write
        from backend.sync_job import _get_sync_state, _set_sync_complete

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u3', 'h', 1)"
            )
            user_id = cur.lastrowid

        now_iso = datetime.now(UTC).isoformat()
        _set_sync_complete(user_id, now_iso)
        state = _get_sync_state(user_id)
        assert state["status"] == "idle"
        assert state["last_synced_at"] == now_iso

    def test_set_sync_complete_updates_existing(self, test_db):
        from backend.database import db_write
        from backend.sync_job import _get_sync_state, _set_sync_complete, _set_sync_status

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u4', 'h', 1)"
            )
            user_id = cur.lastrowid

        _set_sync_status(user_id, "syncing")
        now_iso = datetime.now(UTC).isoformat()
        _set_sync_complete(user_id, now_iso)
        state = _get_sync_state(user_id)
        assert state["status"] == "idle"


class TestFindExistingFlight:
    def _insert_user(self, conn):
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES ('pilot', 'h', 1)"
        )
        return cur.lastrowid

    def test_no_flight_returns_none(self, test_db):
        from backend.flight_store import find_existing_flight as _find_existing_flight

        result = _find_existing_flight("LA1234", "2025-06-01", 1)
        assert result is None

    def test_finds_flight_by_number_and_date(self, test_db):
        import uuid

        from backend.database import db_write
        from backend.flight_store import find_existing_flight as _find_existing_flight

        now = datetime.now(UTC).isoformat()
        with db_write() as conn:
            user_id = self._insert_user(conn)
            fid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
                "arrival_airport, arrival_datetime, is_manually_added, user_id, created_at, updated_at) "
                "VALUES (?, 'LA1234', 'GRU', '2025-06-01T10:00:00+00:00', 'LHR', '2025-06-01T22:00:00+00:00', 0, ?, ?, ?)",
                (fid, user_id, now, now),
            )

        result = _find_existing_flight("LA1234", "2025-06-01", user_id)
        assert result is not None
        assert result["flight_number"] == "LA1234"

    def test_manual_flight_not_found(self, test_db):
        import uuid

        from backend.database import db_write
        from backend.flight_store import find_existing_flight as _find_existing_flight

        now = datetime.now(UTC).isoformat()
        with db_write() as conn:
            user_id = self._insert_user(conn)
            conn.execute(
                "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
                "arrival_airport, arrival_datetime, is_manually_added, user_id, created_at, updated_at) "
                "VALUES (?, 'LA1234', 'GRU', '2025-06-01T10:00:00+00:00', 'LHR', '2025-06-01T22:00:00+00:00', 1, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, now, now),
            )

        result = _find_existing_flight("LA1234", "2025-06-01", user_id)
        assert result is None


class TestInsertFlight:
    def test_insert_new_flight(self, test_db):
        import uuid

        from backend.database import db_conn, db_write
        from backend.flight_store import insert_flight as _insert_flight

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u', 'h', 1)"
            )
            user_id = cur.lastrowid

        email_msg = _make_email_msg(message_id="<unique-msg-id@test.com>")
        flight_data = {
            "flight_number": "LA8094",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2025, 6, 1, 22, 0, 0, tzinfo=UTC),
        }

        flight_id = _insert_flight(flight_data, email_msg, user_id)
        assert flight_id is not None

        with db_conn() as conn:
            row = conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
        assert row is not None
        assert row["flight_number"] == "LA8094"

    def test_duplicate_message_id_returns_none(self, test_db):
        from backend.database import db_write
        from backend.flight_store import insert_flight as _insert_flight

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u2', 'h', 1)"
            )
            user_id = cur.lastrowid

        email_msg = _make_email_msg(message_id="<dup-msg@test.com>")
        flight_data = {
            "flight_number": "LA1111",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2025, 6, 1, 22, 0, 0, tzinfo=UTC),
        }

        fid1 = _insert_flight(flight_data, email_msg, user_id)
        fid2 = _insert_flight(flight_data, email_msg, user_id)
        assert fid1 is not None
        assert fid2 is None  # duplicate

    def test_status_completed_for_past_flight(self, test_db):
        from backend.database import db_conn, db_write
        from backend.flight_store import insert_flight as _insert_flight

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u3', 'h', 1)"
            )
            user_id = cur.lastrowid

        email_msg = _make_email_msg(message_id="<past-flight@test.com>")
        flight_data = {
            "flight_number": "LA2222",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2020, 1, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2020, 1, 1, 22, 0, 0, tzinfo=UTC),
        }

        fid = _insert_flight(flight_data, email_msg, user_id)
        with db_conn() as conn:
            row = conn.execute("SELECT status FROM flights WHERE id = ?", (fid,)).fetchone()
        assert row["status"] == "completed"


class TestUpdateFlightFromBcbp:
    def test_updates_seat_and_cabin(self, test_db):
        import uuid

        from backend.database import db_conn, db_write
        from backend.flight_store import update_flight_from_bcbp as _update_flight_from_bcbp

        now = datetime.now(UTC).isoformat()
        fid = str(uuid.uuid4())
        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u', 'h', 1)"
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
                "arrival_airport, arrival_datetime, user_id, created_at, updated_at) "
                "VALUES (?, 'LA1', 'GRU', '2025-06-01T10:00:00', 'LHR', '2025-06-01T22:00:00', ?, ?, ?)",
                (fid, user_id, now, now),
            )

        _update_flight_from_bcbp(fid, {"seat": "22A", "cabin_class": "economy"})

        with db_conn() as conn:
            row = conn.execute(
                "SELECT seat, cabin_class FROM flights WHERE id = ?", (fid,)
            ).fetchone()
        assert row["seat"] == "22A"
        assert row["cabin_class"] == "economy"

    def test_empty_bcbp_data_no_update(self, test_db):
        """If bcbp data has no relevant fields, no update is executed."""
        from backend.flight_store import update_flight_from_bcbp as _update_flight_from_bcbp

        # Should not raise even with no updates
        _update_flight_from_bcbp("nonexistent-id", {})


class TestProcessBcbpEmail:
    def test_no_body_returns_zero(self, test_db):
        from backend.sync_job import _process_bcbp_email

        email_msg = _make_email_msg(body="")
        legs, updated = _process_bcbp_email(email_msg, 1)
        assert legs == 0
        assert updated == 0

    def test_body_without_bcbp_returns_zero(self, test_db):
        from backend.sync_job import _process_bcbp_email

        email_msg = _make_email_msg(body="Hello, your flight is confirmed.")
        legs, updated = _process_bcbp_email(email_msg, 1)
        assert legs == 0
        assert updated == 0


class TestResetAutoFlights:
    def test_reset_removes_auto_flights(self, test_db):
        import uuid

        from backend.database import db_conn, db_write
        from backend.sync_job import reset_auto_flights

        now = datetime.now(UTC).isoformat()
        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u', 'h', 1)"
            )
            user_id = cur.lastrowid
            # Insert an auto-generated trip
            tid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO trips (id, name, is_auto_generated, user_id, created_at, updated_at) "
                "VALUES (?, 'Auto Trip', 1, ?, ?, ?)",
                (tid, user_id, now, now),
            )
            # Insert an auto-generated flight
            fid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
                "arrival_airport, arrival_datetime, is_manually_added, user_id, created_at, updated_at) "
                "VALUES (?, 'LA1', 'GRU', '2025-06-01T10:00:00', 'LHR', '2025-06-01T22:00:00', 0, ?, ?, ?)",
                (fid, user_id, now, now),
            )

        result = reset_auto_flights(user_id)
        assert "deleted_flights" in result
        assert result["deleted_flights"] >= 1

        with db_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM flights WHERE id = ?", (fid,)).fetchone()[0]
        assert count == 0

    def test_reset_preserves_manual_flights(self, test_db):
        import uuid

        from backend.database import db_conn, db_write
        from backend.sync_job import reset_auto_flights

        now = datetime.now(UTC).isoformat()
        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u2', 'h', 1)"
            )
            user_id = cur.lastrowid
            fid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
                "arrival_airport, arrival_datetime, is_manually_added, user_id, created_at, updated_at) "
                "VALUES (?, 'LA2', 'GRU', '2025-06-01T10:00:00', 'LHR', '2025-06-01T22:00:00', 1, ?, ?, ?)",
                (fid, user_id, now, now),
            )

        reset_auto_flights(user_id)

        with db_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM flights WHERE id = ?", (fid,)).fetchone()[0]
        assert count == 1  # manual flight still exists
