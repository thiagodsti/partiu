"""Domain-level errors for the boarding-passes feature.

Shared by repository.py (raises AccessDeniedError on path traversal) and service.py
(raises the rest) so routes.py can translate each to the exact HTTP response the
original inline route handlers produced.
"""


class BoardingPassError(Exception):
    """Base class for all boarding-pass domain errors."""


class TripAccessError(BoardingPassError):
    """User cannot access the given trip."""


class FlightAccessError(BoardingPassError):
    """User cannot read or does not own the given flight."""


class BoardingPassNotFoundError(BoardingPassError):
    """No boarding pass exists for the given id (or the user can't access it)."""


class ImageNotFoundError(BoardingPassError):
    """The boarding pass exists but its image file is missing."""


class AccessDeniedError(BoardingPassError):
    """A stored file path resolved outside the boarding-pass storage directory."""


class UnsupportedFileTypeError(BoardingPassError):
    def __init__(self, content_type: str | None):
        self.content_type = content_type
        super().__init__(f"Unsupported file type: {content_type}. Use PNG or JPEG.")


class FileTooLargeError(BoardingPassError):
    def __init__(self):
        super().__init__("File too large (max 10 MB)")


class FileTooSmallError(BoardingPassError):
    def __init__(self):
        super().__init__("File is empty or too small")
