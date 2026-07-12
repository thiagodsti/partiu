"""Domain object for the trip day-notes (planner) feature."""

from dataclasses import dataclass


@dataclass
class DayNote:
    date: str
    content: str
    updated_at: str
    updated_by_username: str | None
