"""Tests for backend.notifications.push_service (send_push, VAPID mgmt, preferences)."""

import itertools
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

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


class TestSendPush:
    def test_returns_zero_when_vapid_not_configured(self, test_db, monkeypatch):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        assert push_service.send_push(user_id, {"title": "test", "body": "test", "url": "/"}) == 0

    def test_returns_zero_when_no_subscriptions(self, test_db, monkeypatch):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fake_private")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fake_public")
        assert push_service.send_push(user_id, {"title": "test", "body": "test", "url": "/"}) == 0

    def test_sends_to_all_subscriptions(self, test_db, monkeypatch):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        for i in range(2):
            push_service.subscribe(
                user_id, PushSubscription(f"https://fcm.example.com/{i}", f"p{i}", f"a{i}")
            )

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fake_private")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fake_public")

        with patch("pywebpush.webpush") as mock_wp:
            mock_wp.return_value = None
            sent = push_service.send_push(user_id, {"title": "test", "body": "body", "url": "/"})

        assert sent == 2

    def test_removes_dead_endpoint_on_404(self, test_db, monkeypatch):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        push_service.subscribe(user_id, PushSubscription("https://fcm.example.com/dead", "p", "a"))

        import backend.config as cfg

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "fake_private")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "fake_public")

        from pywebpush import WebPushException

        mock_response = MagicMock()
        mock_response.status_code = 410

        exc = WebPushException("Gone", response=mock_response)

        with patch("pywebpush.webpush", side_effect=exc):
            sent = push_service.send_push(user_id, {"title": "t", "body": "b", "url": "/"})

        assert sent == 0
        assert push_service.get_subscriptions(user_id) == []


class TestVapidKeys:
    def test_effective_keys_from_env(self, monkeypatch):
        import backend.config as cfg
        from backend.notifications.push_service import push_service

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "pub")
        keys = push_service.get_effective_vapid_keys()
        assert keys.source == "env"
        assert keys.private_key == "priv"

    def test_effective_keys_none_when_unconfigured(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.notifications.push_service import push_service

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")
        keys = push_service.get_effective_vapid_keys()
        assert keys.source == "none"

    def test_generate_and_store_vapid_keys(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.notifications.push_service import push_service

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")

        keys = push_service.generate_and_store_vapid_keys()
        assert keys.source == "database"
        assert len(keys.public_key) > 10

        # Persisted — reading effective keys again should reflect it
        stored = push_service.get_effective_vapid_keys()
        assert stored.public_key == keys.public_key

    def test_ensure_vapid_keys_generates_when_missing(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.notifications.push_service import push_service

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "")

        push_service.ensure_vapid_keys()
        keys = push_service.get_effective_vapid_keys()
        assert keys.source == "database"
        assert keys.public_key

    def test_ensure_vapid_keys_noop_when_env_configured(self, test_db, monkeypatch):
        import backend.config as cfg
        from backend.notifications.push_service import push_service

        monkeypatch.setattr(cfg.settings, "VAPID_PRIVATE_KEY", "envpriv")
        monkeypatch.setattr(cfg.settings, "VAPID_PUBLIC_KEY", "envpub")

        push_service.ensure_vapid_keys()  # should not raise, should not touch DB
        keys = push_service.get_effective_vapid_keys()
        assert keys.source == "env"


class TestPreferences:
    def test_update_preferences_applies_only_valid_keys(self, test_db):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        applied = push_service.update_preferences(
            user_id, {"flight_reminder": False, "unknown_field": True}
        )
        assert applied == {"flight_reminder": False}

    def test_update_preferences_raises_when_no_valid_fields(self, test_db):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        with pytest.raises(ValueError):
            push_service.update_preferences(user_id, {"unknown_field": True})

    def test_is_preference_enabled_defaults_to_true(self, test_db):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        assert push_service.is_preference_enabled(user_id, "boarding_pass") is True

    def test_is_preference_enabled_reflects_update(self, test_db):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        push_service.update_preferences(user_id, {"new_flight": False})
        assert push_service.is_preference_enabled(user_id, "new_flight") is False

    def test_get_locale_defaults_to_en(self, test_db):
        from backend.notifications.push_service import push_service

        user_id = _seed_user(test_db)
        assert push_service.get_locale(user_id) == "en"

    def test_preferences_from_user_reads_dict_fields(self):
        from backend.notifications.push_service import push_service

        user = {
            "notif_flight_reminder": 0,
            "notif_checkin_reminder": 1,
            "notif_trip_reminder": 1,
            "notif_delay_alert": 1,
            "notif_boarding_pass": 1,
            "notif_new_flight": 1,
        }
        prefs = push_service.preferences_from_user(user)
        assert prefs.flight_reminder is False
        assert prefs.checkin_reminder is True
