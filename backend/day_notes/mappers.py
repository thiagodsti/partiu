"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import DayNote
from .dto import DayNoteDTO


def row_to_day_note(row: sqlite3.Row) -> DayNote:
    return DayNote(
        date=row["date"],
        content=row["content"],
        updated_at=row["updated_at"],
        updated_by_username=row["updated_by_username"],
    )


def day_note_to_dto(note: DayNote) -> DayNoteDTO:
    return DayNoteDTO(
        date=note.date,
        content=note.content,
        updated_at=note.updated_at,
        updated_by_username=note.updated_by_username,
    )
