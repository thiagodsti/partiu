"""Tests for backend.notifications.push_repository (subscriptions, dedup log, vapid storage, badge)."""

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


class TestSaveSubscription:
    def test_save_new_subscription(self, test_db):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.save_subscription(
            user_id, PushSubscription("https://fcm.example.com/abc", "p256", "authval")
        )

        subs = repo.get_subscriptions(user_id)
        assert len(subs) == 1
        assert subs[0].endpoint == "https://fcm.example.com/abc"
        assert subs[0].p256dh == "p256"
        assert subs[0].auth == "authval"

    def test_upsert_updates_keys(self, test_db):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.save_subscription(
            user_id, PushSubscription("https://fcm.example.com/abc", "old", "old")
        )
        repo.save_subscription(
            user_id, PushSubscription("https://fcm.example.com/abc", "new", "new")
        )

        subs = repo.get_subscriptions(user_id)
        assert len(subs) == 1
        assert subs[0].p256dh == "new"

    def test_multiple_devices(self, test_db):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        for i in range(3):
            repo.save_subscription(
                user_id, PushSubscription(f"https://fcm.example.com/{i}", f"p{i}", f"a{i}")
            )

        assert len(repo.get_subscriptions(user_id)) == 3


class TestDeleteSubscription:
    def test_delete_existing(self, test_db):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.save_subscription(user_id, PushSubscription("https://fcm.example.com/del", "p", "a"))

        repo.delete_subscription(user_id, "https://fcm.example.com/del")
        assert repo.get_subscriptions(user_id) == []

    def test_delete_nonexistent_is_noop(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.delete_subscription(user_id, "https://notexist.com")  # should not raise


class TestGetSubscriptions:
    def test_empty_for_new_user(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        assert repo.get_subscriptions(user_id) == []

    def test_isolates_by_user(self, test_db):
        from backend.notifications.domain import PushSubscription
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        uid1 = _seed_user(test_db)
        uid2 = _seed_user(test_db)
        repo.save_subscription(uid1, PushSubscription("https://fcm.example.com/x", "p", "a"))

        assert len(repo.get_subscriptions(uid1)) == 1
        assert repo.get_subscriptions(uid2) == []


class TestUnreadBadge:
    def test_get_unread_count_defaults_to_zero(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        assert repo.get_unread_count(user_id) == 0

    def test_increment_unread(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        assert repo.increment_unread(user_id) == 1
        assert repo.increment_unread(user_id) == 2

    def test_clear_unread(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.increment_unread(user_id)
        repo.clear_unread(user_id)
        assert repo.get_unread_count(user_id) == 0


class TestDeduplicationLog:
    def test_already_sent_false_initially(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        assert repo.already_sent(user_id, "flight-1", "flight_reminder") is False

    def test_log_sent_marks_as_sent(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.log_sent(user_id, "flight-1", "flight_reminder")
        assert repo.already_sent(user_id, "flight-1", "flight_reminder") is True

    def test_log_sent_idempotent(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.log_sent(user_id, "flight-1", "checkin_reminder")
        repo.log_sent(user_id, "flight-1", "checkin_reminder")  # should not raise
        assert repo.already_sent(user_id, "flight-1", "checkin_reminder") is True

    def test_different_types_are_independent(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.log_sent(user_id, "flight-1", "flight_reminder")
        assert repo.already_sent(user_id, "flight-1", "checkin_reminder") is False


class TestVapidStorage:
    def test_get_vapid_settings_empty_by_default(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        private, public, subject = repo.get_vapid_settings()
        assert private == ""
        assert public == ""

    def test_save_and_read_back_vapid_keys(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        repo.save_vapid_keys("priv123", "pub123")
        private, public, _ = repo.get_vapid_settings()
        assert private == "priv123"
        assert public == "pub123"


class TestIsEnabled:
    def test_defaults_to_true(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        assert repo.is_enabled(user_id, "boarding_pass") is True

    def test_false_after_disabling(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.update_preferences(user_id, {"new_flight": False})
        assert repo.is_enabled(user_id, "new_flight") is False

    def test_false_for_unknown_user(self, test_db):
        from backend.notifications.push_repository import PushRepository

        assert PushRepository().is_enabled(99999, "boarding_pass") is False


class TestGetLocale:
    def test_defaults_to_en(self, test_db):
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        assert repo.get_locale(user_id) == "en"

    def test_reads_configured_locale(self, test_db):
        from backend.database import db_write
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        with db_write() as conn:
            conn.execute("UPDATE users SET locale = ? WHERE id = ?", ("pt-BR", user_id))

        assert repo.get_locale(user_id) == "pt-BR"

    def test_defaults_to_en_for_unknown_user(self, test_db):
        from backend.notifications.push_repository import PushRepository

        assert PushRepository().get_locale(99999) == "en"


class TestUpdatePreferences:
    def test_updates_only_given_columns(self, test_db):
        from backend.database import db_conn
        from backend.notifications.push_repository import PushRepository

        repo = PushRepository()
        user_id = _seed_user(test_db)
        repo.update_preferences(user_id, {"flight_reminder": False, "checkin_reminder": True})

        with db_conn() as conn:
            row = conn.execute(
                "SELECT notif_flight_reminder, notif_checkin_reminder FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        assert row["notif_flight_reminder"] == 0
        assert row["notif_checkin_reminder"] == 1
