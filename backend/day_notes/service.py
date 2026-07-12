"""Use cases for trip day notes: trip-access checks + date-format validation."""

import re

from .domain import DayNote
from .repository import DayNoteRepository

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TripAccessError(Exception):
    """Raised when the user cannot access the given trip."""


class InvalidDateError(Exception):
    """Raised when the given date isn't in YYYY-MM-DD format."""


class DayNoteService:
    def __init__(self, repository: DayNoteRepository | None = None):
        self._repository = repository or DayNoteRepository()

    def list_notes(self, trip_id: str, user_id: int) -> list[DayNote]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def upsert_note(self, trip_id: str, date: str, content: str, user_id: int) -> None:
        """Validation runs before the trip-access check (matches the original route's
        behavior: a malformed date on someone else's trip returns 422, not 404)."""
        if not _DATE_RE.match(date):
            raise InvalidDateError(date)

        self._check_access(trip_id, user_id)
        self._repository.upsert(trip_id, date, content, user_id)

    def _check_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


day_note_service = DayNoteService()
