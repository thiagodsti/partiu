"""Tests for backend.notifications.repository (in-app notification inbox CRUD)."""

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


class TestCreate:
    def test_create_returns_id_and_is_listed(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        notif_id = repo.create(user_id, "new_flight", "Title", "Body", "/#/trips")

        notifications = repo.list_for_user(user_id)
        assert len(notifications) == 1
        assert notifications[0].id == notif_id
        assert notifications[0].title == "Title"
        assert notifications[0].body == "Body"
        assert notifications[0].url == "/#/trips"
        assert notifications[0].read is False

    def test_create_bumps_unread_badge_counter(self, test_db):
        from backend.database import db_conn
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        repo.create(user_id, "new_flight", "Title")

        with db_conn() as conn:
            row = conn.execute("SELECT notif_unread FROM users WHERE id = ?", (user_id,)).fetchone()
        assert row["notif_unread"] == 1

    def test_create_caps_inbox_at_max_per_user(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        for i in range(105):
            repo.create(user_id, "new_flight", f"Title {i}")

        assert len(repo.list_for_user(user_id, limit=1000)) == 100


class TestListForUser:
    def test_orders_newest_first(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        repo.create(user_id, "new_flight", "First")
        repo.create(user_id, "new_flight", "Second")

        notifications = repo.list_for_user(user_id)
        assert notifications[0].title == "Second"
        assert notifications[1].title == "First"

    def test_isolates_by_user(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        uid1 = _seed_user(test_db)
        uid2 = _seed_user(test_db)
        repo.create(uid1, "new_flight", "For user 1")

        assert len(repo.list_for_user(uid1)) == 1
        assert repo.list_for_user(uid2) == []


class TestUnreadCount:
    def test_counts_only_unread(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        nid = repo.create(user_id, "new_flight", "Title")
        repo.create(user_id, "new_flight", "Title 2")

        assert repo.count_unread(user_id) == 2
        repo.mark_read(nid, user_id)
        assert repo.count_unread(user_id) == 1


class TestMarkRead:
    def test_mark_read_returns_true_when_found(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        nid = repo.create(user_id, "new_flight", "Title")

        assert repo.mark_read(nid, user_id) is True
        assert repo.list_for_user(user_id)[0].read is True

    def test_mark_read_returns_false_when_not_found(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        assert repo.mark_read(9999, user_id) is False

    def test_mark_read_scoped_to_user(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        uid1 = _seed_user(test_db)
        uid2 = _seed_user(test_db)
        nid = repo.create(uid1, "new_flight", "Title")

        assert repo.mark_read(nid, uid2) is False


class TestMarkAllRead:
    def test_marks_all_unread_and_returns_count(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        repo.create(user_id, "new_flight", "A")
        repo.create(user_id, "new_flight", "B")

        assert repo.mark_all_read(user_id) == 2
        assert repo.count_unread(user_id) == 0


class TestDelete:
    def test_delete_existing_returns_true(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        nid = repo.create(user_id, "new_flight", "Title")

        assert repo.delete(nid, user_id) is True
        assert repo.list_for_user(user_id) == []

    def test_delete_nonexistent_returns_false(self, test_db):
        from backend.notifications.repository import NotificationRepository

        repo = NotificationRepository()
        user_id = _seed_user(test_db)
        assert repo.delete(9999, user_id) is False
