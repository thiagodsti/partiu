"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import TripDocument
from .dto import TripDocumentDTO


def row_to_document(row: sqlite3.Row) -> TripDocument:
    return TripDocument(
        id=row["id"],
        trip_id=row["trip_id"],
        filename=row["filename"],
        file_path=row["file_path"],
        mime_type=row["mime_type"],
        file_size=row["file_size"],
        page_count=row["page_count"],
        created_at=row["created_at"],
    )


def document_to_dto(doc: TripDocument) -> TripDocumentDTO:
    return TripDocumentDTO(
        id=doc.id,
        trip_id=doc.trip_id,
        filename=doc.filename,
        mime_type=doc.mime_type,
        file_size=doc.file_size,
        page_count=doc.page_count,
        created_at=doc.created_at,
    )
