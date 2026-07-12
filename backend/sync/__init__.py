"""
Sync-control feature package (manual sync/regroup triggers, status, .eml upload),
plus the email sync pipeline itself.

Layering (routes -> service -> repository -> database):
  routes.py       - FastAPI router; only HTTP concerns, delegates to SyncService
  dto.py          - response models used at the HTTP boundary (routes)
  domain.py       - plain domain objects used by the service/repository
  mappers.py      - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py    - SyncRepository: reads/writes `email_sync_state` and
                       `processed_emails` (dedup tracking), reads user IMAP credentials
  service.py         - SyncService: owns the process-wide sync lock, composes status,
                          triggers the background sync job (pipeline.py), imports
                          uploaded .eml files
  pipeline.py         - The actual IMAP fetch -> parse -> persist -> group pipeline;
                          also the entry point for scheduled sync (scheduler.py) and
                          inbound SMTP email (smtp_server.py). Not part of the
                          routes/service/repository chain — service.py and those two
                          top-level modules call into it directly.
  grouping.py         - Auto-groups flights into trips by booking reference, then
                          48h time proximity; called from pipeline.py and from
                          SyncService.trigger_regroup()

``sync_service`` is a module-level singleton — it must be, since ``_lock`` (guarding
against two syncs running concurrently) needs to be shared across every request.
"""

from .service import sync_service

__all__ = ["sync_service"]
