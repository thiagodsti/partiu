"""Exceptions for the trip-stays feature."""


class TripAccessError(Exception):
    """Raised when the user cannot access the given trip."""


class StayNotFoundError(Exception):
    """Raised when the stay does not exist for the given trip."""
