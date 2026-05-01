"""
Sync control routes.
"""

import email as stdlib_email
import email.utils
import threading
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile

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


_MAX_EML_SIZE = 10 * 1024 * 1024  # 10 MB per file
_MAX_EML_FILES = 20


@router.post("/upload-eml")
@limiter.limit("20/minute")
async def upload_eml(
    request: Request,
    files: list[UploadFile],
    user: dict = Depends(get_current_user),
):
    """Parse one or more uploaded .eml files and import flights from them."""
    from ..parsers.email_connector import EmailMessage, decode_header_value, get_email_body_and_html
    from ..sync_job import _process_emails

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > _MAX_EML_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files (max {_MAX_EML_FILES})")

    email_messages: list[EmailMessage] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > _MAX_EML_SIZE:
            raise HTTPException(
                status_code=400, detail=f"File {upload.filename!r} exceeds 10 MB limit"
            )

        try:
            msg = stdlib_email.message_from_bytes(raw)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not parse {upload.filename!r}: {exc}"
            ) from exc

        body, html_body, pdf_attachments, ics_texts = get_email_body_and_html(msg)

        date_str = msg.get("Date", "")
        msg_date: datetime | None = None
        if date_str:
            try:
                msg_date = email.utils.parsedate_to_datetime(date_str)
            except Exception:
                pass
        if msg_date is None:
            msg_date = datetime.now(tz=UTC)

        message_id = (
            msg.get("Message-ID") or f"upload-{upload.filename}-{datetime.now(tz=UTC).timestamp()}"
        )

        email_messages.append(
            EmailMessage(
                message_id=message_id,
                sender=decode_header_value(msg.get("From") or ""),
                subject=decode_header_value(msg.get("Subject") or ""),
                body=body,
                date=msg_date,
                html_body=html_body,
                pdf_attachments=pdf_attachments,
                raw_eml=raw,
                ics_texts=ics_texts,
            )
        )

    result = _process_emails(email_messages, user_id=user["id"], use_llm=True)
    return {
        "emails_processed": result["emails_processed"],
        "flights_created": result["flights_created"],
        "flights_updated": result["flights_updated"],
    }
