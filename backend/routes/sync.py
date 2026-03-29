"""
Sync control routes.
"""

import threading

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ..auth import get_current_user
from ..database import db_conn, db_write, get_global_setting
from ..limiter import limiter

router = APIRouter(prefix="/api/sync", tags=["sync"])

_sync_lock = threading.Lock()


@router.get("/status")
def get_sync_status(user: dict = Depends(get_current_user)):
    """Return the current sync state for this user."""
    interval = int(get_global_setting("sync_interval_minutes", "10"))
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM email_sync_state WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
    if not row:
        return {
            "status": "idle",
            "last_synced_at": None,
            "last_error": None,
            "last_rules_version": None,
            "sync_interval_minutes": interval,
        }
    return {**dict(row), "sync_interval_minutes": interval}


@router.post("/now")
@limiter.limit("5/minute")
def sync_now(
    request: Request, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)
):
    """Trigger an immediate email sync (runs in background)."""
    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running", "message": "Sync is already in progress"}

    user_id = user["id"]

    def _run():
        try:
            from ..crypto import decrypt
            from ..database import db_conn
            from ..sync_job import run_email_sync_for_user

            with db_conn() as conn:
                u = conn.execute(
                    "SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            if u:
                user_dict = dict(u)
                if user_dict.get("gmail_app_password"):
                    user_dict["gmail_app_password"] = decrypt(user_dict["gmail_app_password"])
                run_email_sync_for_user(user_dict)
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Sync started in background"}


@router.post("/regroup")
def regroup(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Re-run grouping on all flights (re-creates auto-generated trips)."""
    user_id = user["id"]

    def _run():
        from ..grouping import regroup_all_flights

        regroup_all_flights(user_id=user_id)

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Regrouping started in background"}


def _make_sync_runner(user_id: int):
    """Return a background task function that syncs email for the given user."""

    def _run():
        try:
            from ..crypto import decrypt
            from ..sync_job import run_email_sync_for_user

            with db_conn() as conn:
                u = conn.execute(
                    "SELECT id, gmail_address, gmail_app_password, imap_host, imap_port FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            if u:
                user_dict = dict(u)
                if user_dict.get("gmail_app_password"):
                    user_dict["gmail_app_password"] = decrypt(user_dict["gmail_app_password"])
                run_email_sync_for_user(user_dict)
        finally:
            _sync_lock.release()

    return _run


@router.post("/full-sync")
def full_sync(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """
    Clear last_synced_at and re-sync from the full first_sync_days window,
    without deleting existing flights (duplicates are skipped automatically).
    """
    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running", "message": "Sync is already in progress"}

    user_id = user["id"]
    with db_write() as conn:
        conn.execute(
            "UPDATE email_sync_state SET last_synced_at = NULL WHERE user_id = ?", (user_id,)
        )

    background_tasks.add_task(_make_sync_runner(user_id))
    return {"status": "started", "message": "Full sync started in background"}


@router.get("/cache-info")
def cache_info(user: dict = Depends(get_current_user)):
    """Return metadata about the local email cache (fast — only reads dates, not full content)."""
    import json

    from ..email_cache import _cache_path

    path = _cache_path()
    if not path.exists():
        return {"exists": False, "count": 0, "oldest": None, "newest": None}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not data:
        return {"exists": True, "count": 0, "oldest": None, "newest": None}
    dates = [e["date"] for e in data if e.get("date")]
    oldest = min(dates) if dates else None
    newest = max(dates) if dates else None
    return {"exists": True, "count": len(data), "oldest": oldest, "newest": newest}


@router.post("/from-cache")
def sync_from_cache(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Resync from the local email cache without downloading from Gmail."""
    from ..email_cache import cache_exists

    if not cache_exists():
        return {"status": "error", "message": "No email cache found. Run a full sync first."}

    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running", "message": "Sync is already in progress"}

    user_id = user["id"]

    def _run():
        try:
            from ..email_cache import load_emails
            from ..sync_job import (
                _process_emails,
                _set_sync_complete,
                _set_sync_status,
                _upsert_sync_state,
            )
            from ..utils import now_iso

            emails = load_emails()
            total = len(emails)
            _upsert_sync_state(
                user_id, status="running", last_error="", emails_total=total, emails_processed=0
            )

            def _progress(n: int):
                _upsert_sync_state(user_id, emails_processed=n)

            _process_emails(emails, user_id, use_llm=True, progress_callback=_progress)
            _set_sync_complete(user_id, now_iso())
        except Exception as e:
            from ..sync_job import _set_sync_status

            _set_sync_status(user_id, "error", str(e))
        finally:
            _sync_lock.release()

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Resync from cache started in background"}


@router.post("/reset-and-sync")
def reset_and_sync(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """
    Delete all auto-synced flights/trips for this user, then re-sync from IMAP.
    Use this to fix stale data (wrong durations, timezones, etc.).
    """
    from ..sync_job import reset_auto_flights

    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running", "message": "Sync is already in progress"}

    user_id = user["id"]
    reset_result = reset_auto_flights(user_id=user_id)

    background_tasks.add_task(_make_sync_runner(user_id))
    return {
        "status": "started",
        "message": "Data reset and re-sync from email started",
        **reset_result,
    }
