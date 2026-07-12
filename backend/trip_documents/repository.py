"""Repository for the `trip_documents` table and its on-disk files.

Trip-access authorization for the simple list/upload flows is a cross-cutting concern
handled by the service layer (see backend.auth). The two composite lookups
(`get_readable`, `get_owned`) embed their access check because they need the row's
trip_id (or a join) to do the check in the first place.
"""

import uuid
from pathlib import Path

from ..auth import can_access_trip
from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import TripDocument
from .errors import AccessDeniedError
from .mappers import row_to_document

_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


class TripDocumentRepository:
    def get_storage_dir(self) -> Path:
        from ..config import settings

        doc_dir = Path(settings.DB_PATH).parent / "trip_documents"
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def safe_file_path(self, raw_path: str) -> Path:
        """Resolve a stored path and verify it stays within the storage directory."""
        storage_dir = self.get_storage_dir().resolve()
        resolved = Path(raw_path).resolve()
        if not str(resolved).startswith(str(storage_dir) + "/"):
            raise AccessDeniedError(raw_path)
        return resolved

    def list_for_trip(self, trip_id: str) -> list[TripDocument]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trip_documents WHERE trip_id = ? ORDER BY created_at ASC",
                (trip_id,),
            ).fetchall()
        return [row_to_document(r) for r in rows]

    def can_read_trip(self, trip_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)

    def get_readable(self, doc_id: str, user_id: int) -> TripDocument | None:
        """Return the document if the user has read access (owner or collaborator)."""
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM trip_documents WHERE id = ?", (doc_id,)).fetchone()
            if not row:
                return None
            if not can_access_trip(row["trip_id"], user_id, conn):
                return None
        return row_to_document(row)

    def get_owned(self, doc_id: str, user_id: int) -> TripDocument | None:
        """Return the document only if the user owns its trip."""
        with db_conn() as conn:
            row = conn.execute(
                """SELECT d.* FROM trip_documents d
                   JOIN trips t ON t.id = d.trip_id
                   WHERE d.id = ? AND t.user_id = ?""",
                (doc_id, user_id),
            ).fetchone()
        return row_to_document(row) if row else None

    def save(
        self, *, trip_id: str, filename: str | None, content_type: str, data: bytes
    ) -> TripDocument:
        doc_id = str(uuid.uuid4())
        ext = _EXTENSIONS.get(content_type, ".bin")
        file_path = str(self.get_storage_dir() / f"{doc_id}{ext}")
        Path(file_path).write_bytes(data)

        page_count = self.pdf_page_count(file_path) if content_type == "application/pdf" else 1
        original_name = filename or f"document{ext}"
        created_at = now_iso()

        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_documents
                   (id, trip_id, filename, file_path, mime_type, file_size, page_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id,
                    trip_id,
                    original_name,
                    file_path,
                    content_type,
                    len(data),
                    page_count,
                    created_at,
                ),
            )

        return TripDocument(
            id=doc_id,
            trip_id=trip_id,
            filename=original_name,
            file_path=file_path,
            mime_type=content_type,
            file_size=len(data),
            page_count=page_count,
            created_at=created_at,
        )

    def delete(self, doc_id: str) -> None:
        with db_write() as conn:
            conn.execute("DELETE FROM trip_documents WHERE id = ?", (doc_id,))

    def delete_file(self, raw_path: str) -> None:
        try:
            self.safe_file_path(raw_path).unlink(missing_ok=True)
        except (OSError, AccessDeniedError):
            pass

    def pdf_page_count(self, file_path: str) -> int:
        try:
            import fitz

            doc = fitz.open(file_path)
            count = len(doc)
            doc.close()
            return max(count, 1)
        except Exception:
            return 1

    def render_pdf_page(self, file_path: str, page_num: int) -> bytes:
        import fitz

        doc = fitz.open(file_path)
        page_num = max(0, min(page_num, len(doc) - 1))
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        data = pix.tobytes("png")
        doc.close()
        return data
