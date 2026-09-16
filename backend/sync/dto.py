"""Response DTOs for the sync-control HTTP API (routes.py).

Trigger endpoints (now/regroup/full-sync) take no request body; upload-eml takes raw
multipart files, not JSON, so routes.py reads them directly.
"""

from pydantic import BaseModel


class SyncStatusDTO(BaseModel):
    status: str
    last_synced_at: str | None
    last_error: str | None
    sync_interval_minutes: int
    emails_processed: int | None
    emails_total: int | None


class TriggerResponseDTO(BaseModel):
    status: str
    message: str


class UploadEmlResponseDTO(BaseModel):
    emails_processed: int
    flights_created: int
    flights_updated: int
    # Accommodation read out of schema.org markup. Reported separately because
    # an upload can legitimately contain no flights at all and still have done
    # something — without this the toast reads "nothing found" over an imported
    # hotel booking.
    stays_created: int = 0
