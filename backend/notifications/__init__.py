"""
Notifications feature package.

Layering (routes -> service -> repository -> database):
  routes.py           - FastAPI router; only HTTP concerns, delegates to the services below
  dto.py             - request/response models used at the HTTP boundary (routes)
  domain.py          - plain domain objects used by services/repositories
  mappers.py         - sqlite3.Row -> domain, domain -> DTO conversions
  repository.py       - NotificationRepository: CRUD for the in-app `notifications` table
  push_repository.py  - PushRepository: push subscriptions, VAPID key storage, dedup log,
                         unread badge counter and per-user notification preference columns
  service.py           - NotificationService: in-app inbox use cases
  push_service.py       - PushService: VAPID key management, sending web push, preferences
  reminder_job.py        - scheduled job that checks upcoming flights/trips and triggers reminders

``notification_service`` and ``push_service`` are module-level singletons — the rest of the
backend (sync.pipeline, integrations.aircraft.status_sync, shares routes, scheduler, main) depends on these two
objects rather than reaching into repositories directly.
"""

from .push_service import push_service
from .service import notification_service

__all__ = ["notification_service", "push_service"]
