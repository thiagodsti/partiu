"""Errors raised by the car-rental service, mapped to HTTP status in routes.py."""


class TripAccessError(Exception):
    """The caller cannot see this trip (or it does not exist)."""


class CarRentalNotFoundError(Exception):
    """No such rental on this trip."""
