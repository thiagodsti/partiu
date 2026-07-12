"""Domain-level errors for admin user management, translated to HTTP by routes.py."""


class UsersError(Exception):
    """Base class for all user-management domain errors."""


class ValidationError(UsersError):
    """Bad input — username/password too short, or username already taken."""


class UserNotFoundError(UsersError):
    """No user exists with the given id."""


class SelfDeleteError(UsersError):
    """An admin tried to delete their own account."""
