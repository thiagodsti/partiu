"""
APScheduler setup for the 10-minute email sync job.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    """Start the background scheduler for email sync."""
    global _scheduler

    from .config import settings
    if settings.DISABLE_SCHEDULER:
        logger.info("Scheduler disabled (DISABLE_SCHEDULER=true) — skipping")
        return

    from .aircraft_sync import run_aircraft_sync
    from .database import get_global_setting
    from .sync_job import run_email_sync

    sync_interval = int(get_global_setting('sync_interval_minutes', '10'))

    _scheduler = BackgroundScheduler(
        job_defaults={'coalesce': True, 'max_instances': 1},
        timezone='UTC',
    )

    _scheduler.add_job(
        run_email_sync,
        trigger=IntervalTrigger(minutes=sync_interval),
        id='email_sync',
        name='Email Sync',
        replace_existing=True,
    )

    _scheduler.add_job(
        run_aircraft_sync,
        trigger=IntervalTrigger(hours=24),
        id='aircraft_sync',
        name='Aircraft Sync',
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started — email sync every %d minutes, aircraft sync daily",
        sync_interval,
    )


def stop_scheduler():
    """Stop the background scheduler gracefully."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
