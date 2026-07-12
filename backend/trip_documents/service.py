"""Use cases for trip documents: trip-access checks + upload validation rules."""

from .domain import TripDocument
from .errors import (
    DocumentNotFoundError,
    FileNotFoundOnDiskError,
    FileTooLargeError,
    FileTooSmallError,
    TripAccessError,
    UnsupportedFileTypeError,
)
from .repository import TripDocumentRepository

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

_VIEW_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class TripDocumentService:
    def __init__(self, repository: TripDocumentRepository | None = None):
        self._repository = repository or TripDocumentRepository()

    def list_for_trip(self, trip_id: str, user_id: int) -> list[TripDocument]:
        if not self._repository.can_read_trip(trip_id, user_id):
            raise TripAccessError(trip_id)
        return self._repository.list_for_trip(trip_id)

    def check_upload_allowed(self, trip_id: str, user_id: int, content_type: str | None) -> str:
        """Cheap pre-checks that don't require the (possibly large) file body.

        Returns the normalized content type. Callers should run this before reading
        the upload into memory. Upload uses the same read access as listing — any
        collaborator can upload, not just the trip owner.
        """
        if not self._repository.can_read_trip(trip_id, user_id):
            raise TripAccessError(trip_id)

        normalized = (content_type or "").split(";")[0].strip()
        if normalized not in _ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileTypeError(normalized)
        return normalized

    def save_upload(
        self, trip_id: str, content_type: str, filename: str | None, data: bytes
    ) -> TripDocument:
        if len(data) > _MAX_UPLOAD_BYTES:
            raise FileTooLargeError()
        if len(data) < 10:
            raise FileTooSmallError()

        return self._repository.save(
            trip_id=trip_id, filename=filename, content_type=content_type, data=data
        )

    def get_view(self, doc_id: str, user_id: int, page: int) -> tuple[bytes, str]:
        """Return (image_bytes, media_type). PDFs are rendered per-page as PNG."""
        doc = self._repository.get_readable(doc_id, user_id)
        if doc is None:
            raise DocumentNotFoundError(doc_id)

        file_path = self._repository.safe_file_path(doc.file_path)
        if not file_path.exists():
            raise FileNotFoundOnDiskError(doc_id)

        if doc.mime_type == "application/pdf":
            image_bytes = self._repository.render_pdf_page(str(file_path), page)
            return image_bytes, "image/png"

        suffix = file_path.suffix.lower()
        media_type = _VIEW_MEDIA_TYPES.get(suffix, "image/png")
        return file_path.read_bytes(), media_type

    def delete(self, doc_id: str, user_id: int) -> None:
        doc = self._repository.get_owned(doc_id, user_id)
        if doc is None:
            raise DocumentNotFoundError(doc_id)

        self._repository.delete(doc_id)
        if doc.file_path:
            self._repository.delete_file(doc.file_path)


trip_document_service = TripDocumentService()
