"""Use cases for the in-app notification inbox."""

from .domain import Notification
from .repository import NotificationRepository


class NotificationService:
    def __init__(self, repository: NotificationRepository | None = None):
        self._repository = repository or NotificationRepository()

    def create_notification(
        self,
        user_id: int,
        notif_type: str,
        title: str,
        body: str = "",
        url: str = "/",
    ) -> int:
        return self._repository.create(user_id, notif_type, title, body, url)

    def list_notifications(self, user_id: int, limit: int = 50) -> list[Notification]:
        return self._repository.list_for_user(user_id, limit)

    def get_unread_count(self, user_id: int) -> int:
        return self._repository.count_unread(user_id)

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        return self._repository.mark_read(notification_id, user_id)

    def mark_all_read(self, user_id: int) -> int:
        return self._repository.mark_all_read(user_id)

    def delete_notification(self, notification_id: int, user_id: int) -> bool:
        return self._repository.delete(notification_id, user_id)


notification_service = NotificationService()
