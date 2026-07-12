"""Domain-level errors for the trip-sharing feature, translated to HTTP by
sharing_routes.py."""


class ShareError(Exception):
    """Base class for all trip-sharing domain errors."""


class TripAccessError(ShareError):
    """User is not the owner of the given trip."""


class UserNotFoundError(ShareError):
    """No user exists with the given username."""


class SelfShareError(ShareError):
    """User tried to share a trip with themselves."""


class AlreadySharedError(ShareError):
    """The target user already has accepted access to the trip."""


class InvitationNotFoundError(ShareError):
    """No pending invitation exists for the given id and user."""


class SharedTripNotFoundError(ShareError):
    """No pending or accepted share exists for the given trip and user."""


class SelfTrustError(ShareError):
    """User tried to add themselves as a trusted user."""


class TrustedUserError(ShareError):
    """Unexpected failure while adding a trusted user."""
