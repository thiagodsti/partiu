"""
Trip-documents feature package (user-uploaded PDFs/images attached to a trip).

Layering (routes -> service -> repository -> database + file storage):
  routes.py       - FastAPI router; only HTTP concerns, delegates to TripDocumentService
  dto.py          - response models used at the HTTP boundary (routes)
  domain.py       - plain domain object used by the service/repository
  errors.py       - domain error types shared by repository.py and service.py, translated
                     to HTTP responses by routes.py
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - TripDocumentRepository: CRUD for the `trip_documents` table + the
                       on-disk files + PDF page counting/rendering (pymupdf)
  service.py         - TripDocumentService: trip-access checks + upload validation

``trip_document_service`` is a module-level singleton — routes.py depends on it rather
than reaching into the repository directly.
"""

from .service import trip_document_service

__all__ = ["trip_document_service"]
