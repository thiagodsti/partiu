"""
Failed email queue — saves unparseble emails to DB + disk for later retry.
"""

import logging
import re
import uuid
from pathlib import Path

from .database import db_conn, db_write
from .parsers.builtin_rules import PARSER_VERSION, get_builtin_rules
from .utils import dt_to_iso, now_iso

logger = logging.getLogger(__name__)

_FLIGHT_KEYWORDS = re.compile(
    r'\b(?:itinerar|e-?ticket|booking\s*confirm|flight\s*confirm|'
    r'reserv|check-?in|boarding|[A-Z]{2}\d{3,4})\b',
    re.IGNORECASE,
)


def email_has_flight_keywords(email_msg) -> bool:
    """Return True if the email subject or body looks like a flight-related email."""
    return bool(
        _FLIGHT_KEYWORDS.search(email_msg.subject or "")
        or _FLIGHT_KEYWORDS.search((email_msg.body or "")[:2000])
    )


def detect_airline_hint(email_msg) -> str:
    """Try to guess the airline from the sender domain."""
    m = re.search(r'@([\w.-]+)', email_msg.sender or "")
    return m.group(1).lower() if m else ""


def save_failed_email(user_id: int, email_msg, reason: str) -> None:
    """Persist a failed-to-parse email to the DB and save the raw .eml to disk."""
    failed_id = str(uuid.uuid4())
    airline_hint = detect_airline_hint(email_msg)

    eml_path: str | None = None
    try:
        from .config import settings
        eml_dir = Path(settings.DB_PATH).parent / "failed_emails"
        eml_dir.mkdir(parents=True, exist_ok=True)
        raw = getattr(email_msg, "raw_eml", None)
        if raw:
            eml_path = str(eml_dir / f"{failed_id}.eml")
            Path(eml_path).write_bytes(raw)
    except Exception as e:
        logger.warning("Could not save raw EML for failed email: %s", e)

    try:
        with db_write() as conn:
            existing = conn.execute(
                "SELECT id FROM failed_emails WHERE user_id = ? AND sender = ? AND subject = ?",
                (user_id, email_msg.sender or "", email_msg.subject or ""),
            ).fetchone()
            if existing:
                return
            conn.execute(
                """INSERT OR IGNORE INTO failed_emails
                   (id, user_id, sender, subject, received_at, reason, airline_hint, eml_path, parser_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    failed_id,
                    user_id,
                    email_msg.sender or "",
                    email_msg.subject or "",
                    dt_to_iso(email_msg.date) if email_msg.date else None,
                    reason,
                    airline_hint,
                    eml_path,
                    PARSER_VERSION,
                    now_iso(),
                ),
            )
    except Exception as e:
        logger.warning("Could not save failed email to DB: %s", e)


def retry_one_failed_email_row(row: dict, user_id: int, sorted_rules: list) -> bool:
    """
    Re-parse a single failed_emails row from its saved EML file.

    Returns True if flights were recovered (row deleted from queue),
    False if still failing or no EML file available.
    Raises on unexpected errors — callers decide how to handle them.
    """
    import email as _email_lib
    import email.utils as _eu

    from .flight_store import find_existing_flight, insert_flight
    from .parsers.email_connector import EmailMessage, decode_header_value, get_email_body_and_html
    from .parsers.engine import (
        extract_flights_from_email,
        match_rule_to_email,
        try_generic_pdf_extraction,
    )
    from .timezone_utils import apply_airport_timezones

    eml_path = row.get("eml_path")
    if not eml_path or not Path(eml_path).exists():
        with db_write() as conn:
            conn.execute(
                "UPDATE failed_emails SET last_retried_at = ? WHERE id = ?",
                (now_iso(), row["id"]),
            )
        return False

    raw = Path(eml_path).read_bytes()
    msg = _email_lib.message_from_bytes(raw)

    sender = decode_header_value(msg.get("From", ""))
    subject = decode_header_value(msg.get("Subject", ""))
    message_id = msg.get("Message-ID", f"retry-{row['id']}")

    body, raw_html, pdf_bytes_list = get_email_body_and_html(msg)

    msg_date = None
    date_str = msg.get("Date", "")
    if date_str:
        try:
            msg_date = _eu.parsedate_to_datetime(date_str)
        except Exception:
            pass

    email_msg = EmailMessage(
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        date=msg_date,
        html_body=raw_html,
        pdf_attachments=pdf_bytes_list,
        raw_eml=raw,
    )

    rule = match_rule_to_email(email_msg, sorted_rules)
    flights_data = (
        extract_flights_from_email(email_msg, rule)
        if rule
        else try_generic_pdf_extraction(email_msg)
    )

    if flights_data:
        flights_data = [apply_airport_timezones(f) for f in flights_data]
        for flight_data in flights_data:
            fn = flight_data.get("flight_number", "")
            if not fn:
                continue
            dep_dt = flight_data.get("departure_datetime")
            dep_date = dt_to_iso(dep_dt)[:10] if dep_dt else None
            if dep_date and find_existing_flight(fn, dep_date, user_id):
                continue
            insert_flight(flight_data, email_msg, user_id)

        with db_write() as conn:
            conn.execute("DELETE FROM failed_emails WHERE id = ?", (row["id"],))
        try:
            Path(eml_path).unlink(missing_ok=True)
        except OSError:
            pass
        return True

    with db_write() as conn:
        conn.execute(
            "UPDATE failed_emails SET last_retried_at = ?, parser_version = ? WHERE id = ?",
            (now_iso(), PARSER_VERSION, row["id"]),
        )
    return False


def retry_failed_emails(user_id: int) -> dict:
    """
    Retry all failed emails for a user.

    Called automatically when PARSER_VERSION bumps on a sync.
    Loads raw EML from disk, re-runs the full parse pipeline,
    and removes successfully parsed emails from the queue.

    Returns a summary dict.
    """
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM failed_emails WHERE user_id = ?", (user_id,)
        ).fetchall()

    if not rows:
        return {"retried": 0, "recovered": 0}

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

    retried = 0
    recovered = 0

    for row in rows:
        row = dict(row)
        eml_path = row.get("eml_path")
        if not eml_path or not Path(eml_path).exists():
            logger.debug("No EML file for failed_email %s — skipping retry", row["id"])
            continue

        retried += 1
        try:
            if retry_one_failed_email_row(row, user_id, sorted_rules):
                recovered += 1
                logger.info("Retry recovered flight(s) from failed email %s", row["id"])
        except Exception as e:
            logger.warning("Error retrying failed email %s: %s", row["id"], e)
            with db_write() as conn:
                conn.execute(
                    "UPDATE failed_emails SET last_retried_at = ? WHERE id = ?",
                    (now_iso(), row["id"]),
                )

    logger.info(
        "User %d: Failed email retry: %d retried, %d recovered",
        user_id, retried, recovered,
    )
    return {"retried": retried, "recovered": recovered}
