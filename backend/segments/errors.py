"""Exceptions for the trip-segments feature."""


class TripAccessError(Exception):
    """Raised when the user cannot access the given trip."""


class SegmentNotFoundError(Exception):
    """Raised when the segment does not exist for the given trip."""
