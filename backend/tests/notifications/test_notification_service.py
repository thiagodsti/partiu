"""Tests for backend.notifications.service (in-app notification inbox use cases)."""

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


class TestNotificationService:
    def test_create_and_list(self, test_db):
        from backend.notifications.service import notification_service

        user_id = _seed_user(test_db)
        notification_service.create_notification(user_id, "new_flight", "Title", "Body", "/#/trips")

        notifications = notification_service.list_notifications(user_id)
        assert len(notifications) == 1
        assert notifications[0].title == "Title"

    def test_unread_count_and_mark_read(self, test_db):
        from backend.notifications.service import notification_service

        user_id = _seed_user(test_db)
        notification_service.create_notification(user_id, "new_flight", "Title")
        [notif] = notification_service.list_notifications(user_id)

        assert notification_service.get_unread_count(user_id) == 1
        assert notification_service.mark_read(notif.id, user_id) is True
        assert notification_service.get_unread_count(user_id) == 0

    def test_mark_all_read(self, test_db):
        from backend.notifications.service import notification_service

        user_id = _seed_user(test_db)
        notification_service.create_notification(user_id, "new_flight", "A")
        notification_service.create_notification(user_id, "new_flight", "B")

        assert notification_service.mark_all_read(user_id) == 2
        assert notification_service.get_unread_count(user_id) == 0

    def test_delete_notification(self, test_db):
        from backend.notifications.service import notification_service

        user_id = _seed_user(test_db)
        notification_service.create_notification(user_id, "new_flight", "Title")
        [notif] = notification_service.list_notifications(user_id)

        assert notification_service.delete_notification(notif.id, user_id) is True
        assert notification_service.list_notifications(user_id) == []
