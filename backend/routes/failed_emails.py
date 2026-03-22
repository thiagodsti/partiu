"""
Failed emails API routes.

  GET    /api/failed-emails               — list failed emails for current user
  POST   /api/failed-emails/{id}/retry    — retry parsing one email
  DELETE /api/failed-emails/{id}          — dismiss / delete one

  GET    /api/admin/failed-emails         — admin: all failures grouped by sender
  DELETE /api/admin/failed-emails/sender  — admin: delete all for a sender (body: {"sender": "..."})
  POST   /api/admin/failed-emails/retry-all — admin: retry everything
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..database import db_conn, db_write
from ..utils import now_iso

router = APIRouter(tags=["failed-emails"])


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.get("/api/failed-emails")
def list_failed_emails(user: dict = Depends(get_current_user)):
    """Return the current user's failed emails (newest first)."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT id, sender, subject, received_at, reason, airline_hint,
                      last_retried_at, parser_version, created_at
               FROM failed_emails
               WHERE user_id = ?
               ORDER BY created_at DESC""",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/failed-emails/{email_id}/retry")
def retry_failed_email(email_id: str, user: dict = Depends(get_current_user)):
    """Retry parsing one failed email. Returns the updated record."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM failed_emails WHERE id = ? AND user_id = ?",
            (email_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Failed email not found")

    row = dict(row)
    _retry_one(row, user["id"])

    # Return the updated state (may have been deleted if successful)
    with db_conn() as conn:
        updated = conn.execute(
            "SELECT * FROM failed_emails WHERE id = ?", (email_id,)
        ).fetchone()

    if updated is None:
        return {"status": "recovered"}
    return {"status": "still_failing", "record": dict(updated)}


@router.delete("/api/failed-emails/{email_id}", status_code=204)
def delete_failed_email(email_id: str, user: dict = Depends(get_current_user)):
    """Dismiss a failed email (delete from queue and disk)."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT eml_path FROM failed_emails WHERE id = ? AND user_id = ?",
            (email_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Failed email not found")

    _delete_failed_email_row(email_id, row["eml_path"])


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@router.get("/api/admin/failed-emails")
def admin_list_failed_emails(user: dict = Depends(require_admin)):
    """Admin view: failure counts grouped by sender domain."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT airline_hint AS sender_domain, COUNT(*) AS count,
                      MAX(created_at) AS latest
               FROM failed_emails
               GROUP BY airline_hint
               ORDER BY count DESC""",
        ).fetchall()
    return [dict(r) for r in rows]


class _SenderBody(BaseModel):
    sender: str


@router.delete("/api/admin/failed-emails/sender", status_code=204)
def admin_delete_sender(body: _SenderBody, user: dict = Depends(require_admin)):
    """Admin: delete all failed emails from a given sender domain."""
    from pathlib import Path

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT eml_path FROM failed_emails WHERE airline_hint = ?",
            (body.sender,),
        ).fetchall()

    if not rows:
        return

    with db_write() as conn:
        conn.execute("DELETE FROM failed_emails WHERE airline_hint = ?", (body.sender,))

    for row in rows:
        if row["eml_path"]:
            try:
                Path(row["eml_path"]).unlink(missing_ok=True)
            except OSError:
                pass


@router.post("/api/admin/failed-emails/retry-all")
def admin_retry_all(user: dict = Depends(require_admin)):
    """Admin: retry all failed emails across all users."""
    with db_conn() as conn:
        user_ids = conn.execute(
            "SELECT DISTINCT user_id FROM failed_emails"
        ).fetchall()

    from ..failed_email_queue import retry_failed_emails

    results = {}
    for row in user_ids:
        uid = row["user_id"]
        results[uid] = retry_failed_emails(uid)

    return {"results": results}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_failed_email_row(email_id: str, eml_path: str | None) -> None:
    from pathlib import Path

    with db_write() as conn:
        conn.execute("DELETE FROM failed_emails WHERE id = ?", (email_id,))

    if eml_path:
        try:
            Path(eml_path).unlink(missing_ok=True)
        except OSError:
            pass


def _retry_one(row: dict, user_id: int) -> None:
    """Load raw EML from disk and re-run the parse pipeline."""
    from ..failed_email_queue import retry_one_failed_email_row
    from ..parsers.builtin_rules import get_builtin_rules

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))
    retry_one_failed_email_row(row, user_id, sorted_rules)
