"""Tests for backend.flight_status_sync."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _create_user(conn) -> int:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
        (f"user_{uuid.uuid4().hex[:8]}", "hash", now),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_flight(
    conn,
    flight_id,
    flight_number,
    dep_dt,
    arr_dt,
    status="upcoming",
    live_status=None,
    live_status_fetched_at=None,
    user_id=None,
):
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO flights (id, flight_number, departure_airport, arrival_airport,
           departure_datetime, arrival_datetime, status, live_status,
           live_status_fetched_at, user_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            flight_id,
            flight_number,
            "GRU",
            "SCL",
            dep_dt,
            arr_dt,
            status,
            live_status,
            live_status_fetched_at,
            user_id,
            now,
            now,
        ),
    )


class TestRunFlightStatusSync:
    def test_skips_when_no_api_key(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.flight_status_sync import run_flight_status_sync

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "")
        result = run_flight_status_sync()
        assert result.get("skipped") is True

    def test_no_eligible_flights_returns_zeros(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.flight_status_sync import run_flight_status_sync

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "fake-key")
        result = run_flight_status_sync()
        assert result["attempted"] == 0
        assert result["updated"] == 0

    def test_completed_flights_are_skipped(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.database import db_write
        from backend.flight_status_sync import run_flight_status_sync

        now = datetime.now(UTC)
        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            uid = _create_user(conn)
            _insert_flight(
                conn,
                flight_id,
                "LA800",
                dep_dt=(now - timedelta(hours=5)).isoformat(),
                arr_dt=(now - timedelta(hours=3)).isoformat(),
                status="completed",
                user_id=uid,
            )

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "fake-key")
        result = run_flight_status_sync()
        assert result["attempted"] == 0

    def test_flight_outside_window_is_skipped(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.database import db_write
        from backend.flight_status_sync import run_flight_status_sync

        now = datetime.now(UTC)
        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            uid = _create_user(conn)
            _insert_flight(
                conn,
                flight_id,
                "LA800",
                dep_dt=(now + timedelta(hours=10)).isoformat(),
                arr_dt=(now + timedelta(hours=12)).isoformat(),
                status="upcoming",
                user_id=uid,
            )

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "fake-key")
        result = run_flight_status_sync()
        assert result["attempted"] == 0

    def test_upcoming_flight_in_window_is_checked(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.database import db_conn, db_write
        from backend.flight_status_sync import run_flight_status_sync

        now = datetime.now(UTC)
        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            uid = _create_user(conn)
            _insert_flight(
                conn,
                flight_id,
                "LA800",
                dep_dt=(now + timedelta(hours=2)).isoformat(),
                arr_dt=(now + timedelta(hours=5)).isoformat(),
                status="upcoming",
                user_id=uid,
            )

        mock_status = {
            "flight_status": "scheduled",
            "departure_delay": 30,
            "arrival_delay": 25,
            "departure_actual": "",
            "arrival_estimated": "",
        }

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "fake-key")
        with (
            patch(
                "backend.flight_status_sync._fetch_status_from_aviationstack",
                new=AsyncMock(return_value=mock_status),
            ),
            patch("backend.flight_status_sync._maybe_send_alert"),
        ):
            result = run_flight_status_sync()

        assert result["attempted"] == 1
        assert result["updated"] == 1

        with db_conn() as conn:
            row = conn.execute(
                "SELECT live_status, live_departure_delay, live_arrival_delay, live_status_fetched_at "
                "FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchone()

        assert row["live_status"] == "scheduled"
        assert row["live_departure_delay"] == 30
        assert row["live_arrival_delay"] == 25
        assert row["live_status_fetched_at"] is not None

    def test_recently_checked_flight_is_skipped(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.database import db_write
        from backend.flight_status_sync import run_flight_status_sync

        now = datetime.now(UTC)
        flight_id = str(uuid.uuid4())
        recent_fetch = (now - timedelta(minutes=5)).isoformat()
        with db_write() as conn:
            uid = _create_user(conn)
            _insert_flight(
                conn,
                flight_id,
                "LA800",
                dep_dt=(now + timedelta(hours=2)).isoformat(),
                arr_dt=(now + timedelta(hours=5)).isoformat(),
                status="upcoming",
                live_status_fetched_at=recent_fetch,
                user_id=uid,
            )

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "fake-key")
        result = run_flight_status_sync()
        assert result["attempted"] == 0

    def test_cancelled_status_is_stored(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.database import db_conn, db_write
        from backend.flight_status_sync import run_flight_status_sync

        now = datetime.now(UTC)
        flight_id = str(uuid.uuid4())
        with db_write() as conn:
            uid = _create_user(conn)
            _insert_flight(
                conn,
                flight_id,
                "LA800",
                dep_dt=(now + timedelta(hours=1)).isoformat(),
                arr_dt=(now + timedelta(hours=3)).isoformat(),
                status="upcoming",
                user_id=uid,
            )

        mock_status = {
            "flight_status": "cancelled",
            "departure_delay": None,
            "arrival_delay": None,
            "departure_actual": "",
            "arrival_estimated": "",
        }

        monkeypatch.setattr(cfg.settings, "AVIATIONSTACK_API_KEY", "fake-key")
        with (
            patch(
                "backend.flight_status_sync._fetch_status_from_aviationstack",
                new=AsyncMock(return_value=mock_status),
            ),
            patch("backend.flight_status_sync._maybe_send_alert"),
        ):
            run_flight_status_sync()

        with db_conn() as conn:
            row = conn.execute(
                "SELECT live_status FROM flights WHERE id = ?", (flight_id,)
            ).fetchone()

        assert row["live_status"] == "cancelled"


class TestMaybeSendAlert:
    def _make_row(self, prev_status=None, prev_dep_delay=0, notif_delay_alert=1):
        """Build a mock row dict like what the DB query returns."""
        return {
            "id": "flight-uuid",
            "flight_number": "LA800",
            "departure_airport": "GRU",
            "arrival_airport": "SCL",
            "trip_id": "trip-uuid",
            "user_id": 1,
            "prev_live_status": prev_status,
            "prev_dep_delay": prev_dep_delay,
            "notif_delay_alert": notif_delay_alert,
        }

    def test_sends_cancelled_alert_on_first_cancellation(self, test_db):
        from backend.flight_status_sync import _maybe_send_alert

        row = self._make_row(prev_status=None)
        status_info = {"flight_status": "cancelled", "departure_delay": None}

        with (
            patch("backend.push.send_push", return_value=1) as mock_push,
            patch("backend.push.already_sent", return_value=False),
            patch("backend.push.log_sent"),
        ):
            _maybe_send_alert(row, status_info)

        mock_push.assert_called_once()
        assert "cancelled" in mock_push.call_args[0][1]["title"].lower()

    def test_does_not_resend_cancelled_alert(self, test_db):
        from backend.flight_status_sync import _maybe_send_alert

        row = self._make_row(prev_status="cancelled")
        status_info = {"flight_status": "cancelled", "departure_delay": None}

        with (
            patch("backend.push.send_push") as mock_push,
            patch("backend.push.already_sent", return_value=False),
        ):
            _maybe_send_alert(row, status_info)

        mock_push.assert_not_called()

    def test_sends_delay_alert_when_threshold_crossed(self, test_db):
        from backend.flight_status_sync import _maybe_send_alert

        row = self._make_row(prev_dep_delay=0)
        status_info = {"flight_status": "scheduled", "departure_delay": 30}

        with (
            patch("backend.push.send_push", return_value=1) as mock_push,
            patch("backend.push.already_sent", return_value=False),
            patch("backend.push.log_sent"),
        ):
            _maybe_send_alert(row, status_info)

        mock_push.assert_called_once()
        assert "30" in mock_push.call_args[0][1]["title"]

    def test_no_delay_alert_below_threshold(self, test_db):
        from backend.flight_status_sync import _maybe_send_alert

        row = self._make_row(prev_dep_delay=0)
        status_info = {"flight_status": "scheduled", "departure_delay": 5}

        with (
            patch("backend.push.send_push") as mock_push,
            patch("backend.push.already_sent", return_value=False),
        ):
            _maybe_send_alert(row, status_info)

        mock_push.assert_not_called()


class TestFetchStatusFromAviationstack:
    def test_returns_empty_on_http_error(self):
        import asyncio

        from backend.flight_status_sync import _fetch_status_from_aviationstack

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("backend.flight_status_sync.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(_fetch_status_from_aviationstack("LA800", "key"))

        assert result == {}

    def test_returns_empty_on_no_data(self):
        import asyncio

        from backend.flight_status_sync import _fetch_status_from_aviationstack

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        with patch("backend.flight_status_sync.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(_fetch_status_from_aviationstack("LA800", "key"))

        assert result == {}

    def test_extracts_delay_and_status(self):
        import asyncio

        from backend.flight_status_sync import _fetch_status_from_aviationstack

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "flight_status": "scheduled",
                    "departure": {
                        "delay": 45,
                        "actual": None,
                        "estimated": "2024-01-15T10:45:00+00:00",
                    },
                    "arrival": {
                        "delay": 30,
                        "actual": None,
                        "estimated": "2024-01-15T14:30:00+00:00",
                    },
                }
            ]
        }

        with patch("backend.flight_status_sync.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = asyncio.run(_fetch_status_from_aviationstack("LA800", "key"))

        assert result["flight_status"] == "scheduled"
        assert result["departure_delay"] == 45
        assert result["arrival_delay"] == 30
