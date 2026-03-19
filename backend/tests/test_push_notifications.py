"""Tests for backend.push_notifications scheduler job."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def _seed_user(db_path: str, notif_flight=1, notif_checkin=1, notif_trip=1) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO users (username, password_hash, is_admin, notif_flight_reminder,
           notif_checkin_reminder, notif_trip_reminder, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("u", "h", 0, notif_flight, notif_checkin, notif_trip, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return uid


def _seed_flight(db_path: str, user_id: int, dep_dt: datetime, trip_id: str | None = None) -> str:
    import sqlite3

    fid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO flights (id, user_id, trip_id, flight_number, departure_airport,
           arrival_airport, departure_datetime, arrival_datetime, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fid,
            user_id,
            trip_id,
            "TS100",
            "GRU",
            "GIG",
            dep_dt.isoformat(),
            dep_dt.isoformat(),
            "upcoming",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return fid


def _seed_trip(db_path: str, user_id: int, start_date: str) -> str:
    import sqlite3

    tid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO trips (id, user_id, name, start_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (tid, user_id, "Test Trip", start_date, now, now),
    )
    conn.commit()
    conn.close()
    return tid


class TestRunPushNotifications:
    def test_no_error_with_no_users(self, test_db):
        from backend.push_notifications import run_push_notifications

        run_push_notifications()  # should not raise

    def test_flight_reminder_sent_in_window(self, test_db, monkeypatch):
        from backend.push_notifications import run_push_notifications

        uid = _seed_user(test_db)
        # departure 2h from now — inside window
        dep = datetime.now(UTC) + timedelta(hours=2)
        fid = _seed_flight(test_db, uid, dep)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            # Seed a subscription
            from backend.push import save_subscription

            save_subscription(
                uid, {"endpoint": "https://e.com/1", "keys": {"p256dh": "p", "auth": "a"}}
            )
            run_push_notifications()

        from backend.push import already_sent

        assert already_sent(uid, fid, "flight_reminder") is True

    def test_flight_reminder_not_sent_outside_window(self, test_db, monkeypatch):
        from backend.push_notifications import run_push_notifications

        uid = _seed_user(test_db)
        # departure 5h from now — outside 2h window
        dep = datetime.now(UTC) + timedelta(hours=5)
        fid = _seed_flight(test_db, uid, dep)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            from backend.push import save_subscription

            save_subscription(
                uid, {"endpoint": "https://e.com/2", "keys": {"p256dh": "p", "auth": "a"}}
            )
            run_push_notifications()

        from backend.push import already_sent

        assert already_sent(uid, fid, "flight_reminder") is False

    def test_checkin_reminder_sent_in_window(self, test_db, monkeypatch):
        from backend.push_notifications import run_push_notifications

        uid = _seed_user(test_db)
        # departure 24h from now
        dep = datetime.now(UTC) + timedelta(hours=24)
        fid = _seed_flight(test_db, uid, dep)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            from backend.push import save_subscription

            save_subscription(
                uid, {"endpoint": "https://e.com/3", "keys": {"p256dh": "p", "auth": "a"}}
            )
            run_push_notifications()

        from backend.push import already_sent

        assert already_sent(uid, fid, "checkin_reminder") is True

    def test_trip_reminder_sent_in_window(self, test_db, monkeypatch):
        from backend.push_notifications import run_push_notifications

        uid = _seed_user(test_db)
        # trip starts in exactly 24h — inside the [23h, 25h] window
        tomorrow = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        tid = _seed_trip(test_db, uid, tomorrow)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            from backend.push import save_subscription

            save_subscription(
                uid, {"endpoint": "https://e.com/4", "keys": {"p256dh": "p", "auth": "a"}}
            )
            run_push_notifications()

        from backend.push import already_sent

        assert already_sent(uid, tid, "trip_reminder") is True

    def test_disabled_notif_not_sent(self, test_db, monkeypatch):
        from backend.push_notifications import run_push_notifications

        uid = _seed_user(test_db, notif_flight=0)
        dep = datetime.now(UTC) + timedelta(hours=2)
        fid_disabled = _seed_flight(test_db, uid, dep)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            from backend.push import save_subscription

            save_subscription(
                uid, {"endpoint": "https://e.com/5", "keys": {"p256dh": "p", "auth": "a"}}
            )
            run_push_notifications()

        from backend.push import already_sent

        assert already_sent(uid, fid_disabled, "flight_reminder") is False

    def test_duplicate_not_sent_twice(self, test_db, monkeypatch):
        from backend.push_notifications import run_push_notifications

        uid = _seed_user(test_db)
        dep = datetime.now(UTC) + timedelta(hours=2)
        _seed_flight(test_db, uid, dep)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")

        from backend.push import save_subscription

        save_subscription(
            uid, {"endpoint": "https://e.com/6", "keys": {"p256dh": "p", "auth": "a"}}
        )

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            run_push_notifications()
            run_push_notifications()

        # webpush should only have been called once for the flight
        flight_calls = [c for c in mock_wp.call_args_list]
        assert len(flight_calls) == 1
