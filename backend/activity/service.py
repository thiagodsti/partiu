"""Use cases for the activity log.

`record` is called from the places that change a user's data in ways they will
later want explained — trash, restore, permanent delete, merge, regroup, full
sync and the parser-version rescan. It must never fail the operation it
describes, so a logging failure is swallowed and reported at warning level.
"""

import logging

from .domain import ActivityEntry
from .repository import ActivityRepository

logger = logging.getLogger(__name__)

MAX_LIMIT = 500


class ActivityService:
    def __init__(self, repository: ActivityRepository | None = None):
        self._repository = repository or ActivityRepository()

    def record(
        self,
        user_id: int,
        action: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        label: str | None = None,
        details: dict | None = None,
    ) -> None:
        try:
            self._repository.record(
                user_id,
                action,
                entity_type=entity_type,
                entity_id=entity_id,
                label=label,
                details=details,
            )
        except Exception as e:  # noqa: BLE001 - the log must never fail the action it records
            logger.warning("User %d: could not record activity %s: %s", user_id, action, e)

    def list_for_user(self, user_id: int, limit: int = 100) -> list[ActivityEntry]:
        return self._repository.list_for_user(user_id, max(1, min(limit, MAX_LIMIT)))


activity_service = ActivityService()
