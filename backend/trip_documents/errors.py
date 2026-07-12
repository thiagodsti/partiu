"""Domain-level errors for the trip-documents feature, translated to HTTP by routes.py."""


class TripDocumentError(Exception):
    """Base class for all trip-document domain errors."""


class TripAccessError(TripDocumentError):
    """User cannot read the given trip."""


class DocumentNotFoundError(TripDocumentError):
    """No document exists for the given id (or the user can't access it)."""


class FileNotFoundOnDiskError(TripDocumentError):
    """The document row exists but its file is missing from disk."""


class AccessDeniedError(TripDocumentError):
    """A stored file path resolved outside the document storage directory."""


class UnsupportedFileTypeError(TripDocumentError):
    def __init__(self, content_type: str | None):
        self.content_type = content_type
        super().__init__(f"Unsupported file type: {content_type}. Use PDF or an image.")


class FileTooLargeError(TripDocumentError):
    def __init__(self):
        super().__init__("File too large (max 20 MB)")


class FileTooSmallError(TripDocumentError):
    def __init__(self):
        super().__init__("File is empty or too small")
