"""Domain objects for the sync-control feature."""

from dataclasses import dataclass


@dataclass
class SyncStateRow:
    """A raw row from ``email_sync_state`` for one user."""

    status: str
    last_synced_at: str | None
    last_error: str | None
    emails_processed: int | None
    emails_total: int | None


@dataclass
class SyncStatus:
    """The composed status returned by GET /api/sync/status."""

    status: str
    last_synced_at: str | None
    last_error: str | None
    sync_interval_minutes: int
    emails_processed: int | None
    emails_total: int | None
