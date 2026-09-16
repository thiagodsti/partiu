"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import SyncStateRow, SyncStatus
from .dto import SyncStatusDTO


def row_to_sync_state(row: sqlite3.Row) -> SyncStateRow:
    return SyncStateRow(
        status=row["status"],
        last_synced_at=row["last_synced_at"],
        last_error=row["last_error"],
        emails_processed=row["emails_processed"],
        emails_total=row["emails_total"],
        parser_version=row["parser_version"] if "parser_version" in row.keys() else "",
    )


def sync_status_to_dto(status: SyncStatus) -> SyncStatusDTO:
    return SyncStatusDTO(
        status=status.status,
        last_synced_at=status.last_synced_at,
        last_error=status.last_error,
        sync_interval_minutes=status.sync_interval_minutes,
        emails_processed=status.emails_processed,
        emails_total=status.emails_total,
    )
