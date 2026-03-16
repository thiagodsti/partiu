"""
Sync control routes.
"""

import threading

from fastapi import APIRouter, BackgroundTasks

from ..database import db_conn

router = APIRouter(prefix='/api/sync', tags=['sync'])

_sync_lock = threading.Lock()


@router.get('/status')
def get_sync_status():
    """Return the current sync state."""
    with db_conn() as conn:
        row = conn.execute('SELECT * FROM email_sync_state WHERE id = 1').fetchone()
    if not row:
        return {'status': 'idle', 'last_synced_at': None, 'last_error': None, 'last_rules_version': None}
    return dict(row)


@router.post('/now')
def sync_now(background_tasks: BackgroundTasks):
    """Trigger an immediate email sync (runs in background)."""
    if not _sync_lock.acquire(blocking=False):
        return {'status': 'already_running', 'message': 'Sync is already in progress'}

    def _run():
        try:
            from ..sync_job import run_email_sync
            run_email_sync()
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {'status': 'started', 'message': 'Sync started in background'}


@router.post('/cached')
def sync_cached(background_tasks: BackgroundTasks):
    """Re-process locally cached emails — no Gmail connection needed."""
    from ..email_cache import cache_exists
    if not cache_exists():
        return {'status': 'error', 'message': 'No email cache found. Run a full sync first.'}

    if not _sync_lock.acquire(blocking=False):
        return {'status': 'already_running', 'message': 'Sync is already in progress'}

    def _run():
        try:
            from ..sync_job import run_cached_sync
            run_cached_sync()
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {'status': 'started', 'message': 'Cached sync started'}


@router.post('/regroup')
def regroup(background_tasks: BackgroundTasks):
    """Re-run grouping on all flights (re-creates auto-generated trips)."""
    def _run():
        from ..grouping import regroup_all_flights
        regroup_all_flights()

    background_tasks.add_task(_run)
    return {'status': 'started', 'message': 'Regrouping started in background'}


@router.post('/reset-and-sync')
def reset_and_sync(background_tasks: BackgroundTasks):
    """
    Delete all auto-synced flights/trips and re-process from cached emails.
    Use this to fix stale data (wrong durations, timezones, etc.).
    """
    from ..sync_job import reset_auto_flights, run_cached_sync
    from ..email_cache import cache_exists

    if not cache_exists():
        return {'status': 'error', 'message': 'No email cache found. Run a full sync first.'}

    if not _sync_lock.acquire(blocking=False):
        return {'status': 'already_running', 'message': 'Sync is already in progress'}

    reset_result = reset_auto_flights()

    def _run():
        try:
            run_cached_sync()
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {
        'status': 'started',
        'message': 'Data reset and re-sync started from cache',
        **reset_result,
    }
