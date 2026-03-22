"""
Sync control routes.
"""

import threading

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ..auth import get_current_user
from ..database import db_conn, get_global_setting
from ..limiter import limiter

router = APIRouter(prefix='/api/sync', tags=['sync'])

_sync_lock = threading.Lock()


@router.get('/status')
def get_sync_status(user: dict = Depends(get_current_user)):
    """Return the current sync state for this user."""
    interval = int(get_global_setting('sync_interval_minutes', '10'))
    with db_conn() as conn:
        row = conn.execute(
            'SELECT * FROM email_sync_state WHERE user_id = ? ORDER BY id DESC LIMIT 1',
            (user['id'],)
        ).fetchone()
    if not row:
        return {'status': 'idle', 'last_synced_at': None, 'last_error': None,
                'last_rules_version': None, 'sync_interval_minutes': interval}
    return {**dict(row), 'sync_interval_minutes': interval}


@router.post('/now')
@limiter.limit("5/minute")
def sync_now(request: Request, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Trigger an immediate email sync (runs in background)."""
    if not _sync_lock.acquire(blocking=False):
        return {'status': 'already_running', 'message': 'Sync is already in progress'}

    user_id = user['id']

    def _run():
        try:
            from ..crypto import decrypt
            from ..database import db_conn
            from ..sync_job import run_email_sync_for_user
            with db_conn() as conn:
                u = conn.execute(
                    'SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users WHERE id = ?',
                    (user_id,)
                ).fetchone()
            if u:
                user_dict = dict(u)
                if user_dict.get("gmail_app_password"):
                    user_dict["gmail_app_password"] = decrypt(user_dict["gmail_app_password"])
                run_email_sync_for_user(user_dict)
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {'status': 'started', 'message': 'Sync started in background'}



@router.post('/regroup')
def regroup(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Re-run grouping on all flights (re-creates auto-generated trips)."""
    user_id = user['id']

    def _run():
        from ..grouping import regroup_all_flights
        regroup_all_flights(user_id=user_id)

    background_tasks.add_task(_run)
    return {'status': 'started', 'message': 'Regrouping started in background'}


@router.post('/reset-and-sync')
def reset_and_sync(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """
    Delete all auto-synced flights/trips for this user, then re-sync from IMAP.
    Use this to fix stale data (wrong durations, timezones, etc.).
    """
    from ..sync_job import reset_auto_flights, run_email_sync_for_user

    if not _sync_lock.acquire(blocking=False):
        return {'status': 'already_running', 'message': 'Sync is already in progress'}

    user_id = user['id']
    reset_result = reset_auto_flights(user_id=user_id)

    def _run():
        try:
            from ..crypto import decrypt
            with db_conn() as conn:
                u = conn.execute(
                    'SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users WHERE id = ?',
                    (user_id,)
                ).fetchone()
            if u:
                user_dict = dict(u)
                if user_dict.get("gmail_app_password"):
                    user_dict["gmail_app_password"] = decrypt(user_dict["gmail_app_password"])
                run_email_sync_for_user(user_dict)
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {
        'status': 'started',
        'message': 'Data reset and re-sync from email started',
        **reset_result,
    }
