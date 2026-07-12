"""Domain-level errors for the settings feature, translated to HTTP by routes.py."""


class SettingsError(Exception):
    """Base class for all settings domain errors."""


class ValidationError(SettingsError):
    """Bad input — SSRF-blocked host/URL, out-of-range value, unsupported currency, etc."""


class SmtpConflictError(SettingsError):
    """The requested SMTP recipient address is already used by another user."""


class AdminRequiredError(SettingsError):
    """Global (admin-only) settings were included in the update by a non-admin."""
