"""Response DTOs for the trip-documents HTTP API (routes.py).

Upload/delete/view are file-based, not JSON-body requests, so there's no request DTO —
routes.py reads the raw UploadFile/path params directly.
"""

from pydantic import BaseModel


class TripDocumentDTO(BaseModel):
    id: str
    trip_id: str
    filename: str
    mime_type: str
    file_size: int
    page_count: int
    created_at: str


class UploadResponseDTO(BaseModel):
    id: str
    page_count: int
