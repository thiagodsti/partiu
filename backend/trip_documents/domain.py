"""Domain object for the trip-documents feature."""

from dataclasses import dataclass


@dataclass
class TripDocument:
    id: str
    trip_id: str
    filename: str
    file_path: str
    mime_type: str
    file_size: int
    page_count: int
    created_at: str
