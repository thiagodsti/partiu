"""Use cases for the trip packing list: trip-access checks + validation rules."""

import uuid

from .domain import PackingItem
from .repository import PackingRepository


class TripAccessError(Exception):
    """Raised when the user cannot access the given trip."""


class PackingItemNotFoundError(Exception):
    """Raised when the packing item does not exist for the given trip."""


class PackingService:
    def __init__(self, repository: PackingRepository | None = None):
        self._repository = repository or PackingRepository()

    def list_items(self, trip_id: str, user_id: int) -> list[PackingItem]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def create_item(self, trip_id: str, user_id: int, text: str) -> str:
        """Create a packing item and return its id."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Item text cannot be empty")

        self._check_access(trip_id, user_id)
        item_id = str(uuid.uuid4())
        self._repository.create(item_id, trip_id, clean_text, user_id)
        return item_id

    def update_item(
        self,
        trip_id: str,
        item_id: str,
        user_id: int,
        text: str | None = None,
        checked: bool | None = None,
    ) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get(item_id, trip_id) is None:
            raise PackingItemNotFoundError(item_id)

        updates: dict = {}
        if text is not None:
            clean_text = text.strip()
            if not clean_text:
                raise ValueError("Item text cannot be empty")
            updates["text"] = clean_text
        if checked is not None:
            updates["checked"] = 1 if checked else 0

        if updates:
            self._repository.update(item_id, trip_id, updates)

    def delete_item(self, trip_id: str, item_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get(item_id, trip_id) is None:
            raise PackingItemNotFoundError(item_id)
        self._repository.delete(item_id, trip_id)

    def clear_checked(self, trip_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        self._repository.clear_checked(trip_id)

    def _check_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


packing_service = PackingService()
