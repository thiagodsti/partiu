"""Tests for backend.push (subscription CRUD, send_push, deduplication log)."""

import itertools
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

_user_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------


class TestSaveSubscription:
    def test_save_new_subscription(self, test_db):
        from backend.push import get_subscriptions, save_subscription

        user_id = _seed_user(test_db)
        sub = {
            "endpoint": "https://fcm.example.com/abc",
            "keys": {"p256dh": "p256", "auth": "authval"},
        }
        save_subscription(user_id, sub, "TestBrowser")

        subs = get_subscriptions(user_id)
        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://fcm.example.com/abc"
        assert subs[0]["p256dh"] == "p256"
        assert subs[0]["auth"] == "authval"

    def test_upsert_updates_keys(self, test_db):
        from backend.push import get_subscriptions, save_subscription

        user_id = _seed_user(test_db)
        sub = {"endpoint": "https://fcm.example.com/abc", "keys": {"p256dh": "old", "auth": "old"}}
        save_subscription(user_id, sub)

        sub2 = {"endpoint": "https://fcm.example.com/abc", "keys": {"p256dh": "new", "auth": "new"}}
        save_subscription(user_id, sub2)

        subs = get_subscriptions(user_id)
        assert len(subs) == 1
        assert subs[0]["p256dh"] == "new"

    def test_multiple_devices(self, test_db):
        from backend.push import get_subscriptions, save_subscription

        user_id = _seed_user(test_db)
        for i in range(3):
            sub = {
                "endpoint": f"https://fcm.example.com/{i}",
                "keys": {"p256dh": f"p{i}", "auth": f"a{i}"},
            }
            save_subscription(user_id, sub)

        subs = get_subscriptions(user_id)
        assert len(subs) == 3


class TestDeleteSubscription:
    def test_delete_existing(self, test_db):
        from backend.push import delete_subscription, get_subscriptions, save_subscription

        user_id = _seed_user(test_db)
        sub = {"endpoint": "https://fcm.example.com/del", "keys": {"p256dh": "p", "auth": "a"}}
        save_subscription(user_id, sub)

        delete_subscription(user_id, "https://fcm.example.com/del")
        assert get_subscriptions(user_id) == []

    def test_delete_nonexistent_is_noop(self, test_db):
        from backend.push import delete_subscription

        user_id = _seed_user(test_db)
        delete_subscription(user_id, "https://notexist.com")  # should not raise


class TestGetSubscriptions:
    def test_empty_for_new_user(self, test_db):
        from backend.push import get_subscriptions

        user_id = _seed_user(test_db)
        assert get_subscriptions(user_id) == []

    def test_isolates_by_user(self, test_db):
        from backend.push import get_subscriptions, save_subscription

        uid1 = _seed_user(test_db)
        uid2 = _seed_user(test_db)
        sub = {"endpoint": "https://fcm.example.com/x", "keys": {"p256dh": "p", "auth": "a"}}
        save_subscription(uid1, sub)

        assert len(get_subscriptions(uid1)) == 1
        assert get_subscriptions(uid2) == []


# ---------------------------------------------------------------------------
# send_push
# ---------------------------------------------------------------------------


class TestSendPush:
    def test_returns_zero_when_vapid_not_configured(self, test_db, monkeypatch):
        from backend.push import send_push

        user_id = _seed_user(test_db)
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        assert send_push(user_id, {"title": "test", "body": "test", "url": "/"}) == 0

    def test_returns_zero_when_no_subscriptions(self, test_db, monkeypatch):
        from backend.push import send_push

        user_id = _seed_user(test_db)
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fake_private")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fake_public")
        assert send_push(user_id, {"title": "test", "body": "test", "url": "/"}) == 0

    def test_sends_to_all_subscriptions(self, test_db, monkeypatch):
        from backend.push import save_subscription, send_push

        user_id = _seed_user(test_db)
        for i in range(2):
            sub = {
                "endpoint": f"https://fcm.example.com/{i}",
                "keys": {"p256dh": f"p{i}", "auth": f"a{i}"},
            }
            save_subscription(user_id, sub)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fake_private")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fake_public")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            sent = send_push(user_id, {"title": "test", "body": "body", "url": "/"})

        assert sent == 2

    def test_removes_dead_endpoint_on_404(self, test_db, monkeypatch):
        from backend.push import get_subscriptions, save_subscription, send_push

        user_id = _seed_user(test_db)
        sub = {"endpoint": "https://fcm.example.com/dead", "keys": {"p256dh": "p", "auth": "a"}}
        save_subscription(user_id, sub)

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fake_private")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fake_public")

        from pywebpush import WebPushException

        mock_response = MagicMock()
        mock_response.status_code = 410

        exc = WebPushException("Gone", response=mock_response)

        with patch("pywebpush.webpush", side_effect=exc):
            sent = send_push(user_id, {"title": "t", "body": "b", "url": "/"})

        assert sent == 0
        assert get_subscriptions(user_id) == []


# ---------------------------------------------------------------------------
# Deduplication log
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_already_sent_false_initially(self, test_db):
        from backend.push import already_sent

        user_id = _seed_user(test_db)
        assert already_sent(user_id, "flight-1", "flight_reminder") is False

    def test_log_sent_marks_as_sent(self, test_db):
        from backend.push import already_sent, log_sent

        user_id = _seed_user(test_db)
        log_sent(user_id, "flight-1", "flight_reminder")
        assert already_sent(user_id, "flight-1", "flight_reminder") is True

    def test_log_sent_idempotent(self, test_db):
        from backend.push import already_sent, log_sent

        user_id = _seed_user(test_db)
        log_sent(user_id, "flight-1", "checkin_reminder")
        log_sent(user_id, "flight-1", "checkin_reminder")  # should not raise
        assert already_sent(user_id, "flight-1", "checkin_reminder") is True

    def test_different_types_are_independent(self, test_db):
        from backend.push import already_sent, log_sent

        user_id = _seed_user(test_db)
        log_sent(user_id, "flight-1", "flight_reminder")
        assert already_sent(user_id, "flight-1", "checkin_reminder") is False
