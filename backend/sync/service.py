"""Use cases for sync control: status lookup, triggering background sync jobs
(guarded by a process-wide lock so only one sync runs at a time), and importing
manually-uploaded .eml files."""

import threading

from .domain import SyncStatus
from .repository import SyncRepository

MAX_EML_SIZE = 10 * 1024 * 1024  # 10 MB per file
MAX_EML_FILES = 20


class EmlParseError(Exception):
    def __init__(self, filename: str | None, original_error: Exception):
        self.filename = filename
        self.original_error = original_error
        super().__init__(f"Could not parse {filename!r}: {original_error}")


class SyncService:
    def __init__(self, repository: SyncRepository | None = None):
        self._repository = repository or SyncRepository()
        self._lock = threading.Lock()

    def get_status(self, user_id: int) -> SyncStatus:
        state = self._repository.get_latest_state(user_id)
        interval = self._repository.get_sync_interval_minutes()
        if state is None:
            return SyncStatus(
                status="idle",
                last_synced_at=None,
                last_error=None,
                sync_interval_minutes=interval,
                emails_processed=None,
                emails_total=None,
            )
        return SyncStatus(
            status=state.status,
            last_synced_at=state.last_synced_at,
            last_error=state.last_error,
            sync_interval_minutes=interval,
            emails_processed=state.emails_processed,
            emails_total=state.emails_total,
        )

    def try_acquire_lock(self) -> bool:
        """Non-blocking; the caller must schedule ``run_sync_for_user`` (which releases
        the lock) if this returns True, or the lock is held forever."""
        return self._lock.acquire(blocking=False)

    def run_sync_for_user(self, user_id: int) -> None:
        """Background job body. Assumes the lock is already held; always releases it."""
        try:
            from ..crypto import decrypt
            from .pipeline import run_email_sync_for_user

            creds = self._repository.get_sync_credentials(user_id)
            if creds:
                creds_dict = dict(creds)
                if creds_dict.get("gmail_app_password"):
                    creds_dict["gmail_app_password"] = decrypt(creds_dict["gmail_app_password"])
                run_email_sync_for_user(creds_dict)
        finally:
            self._lock.release()

    def reset_last_synced(self, user_id: int) -> None:
        self._repository.reset_last_synced(user_id)

    def trigger_regroup(self, user_id: int) -> None:
        from .grouping import regroup_all_flights

        regroup_all_flights(user_id=user_id)

    def import_eml_files(self, files: list[tuple[str | None, bytes]], user_id: int) -> dict:
        """Parse uploaded .eml files into EmailMessage objects and run them through the
        normal sync pipeline. ``files`` is (filename, raw_bytes) pairs already read by
        the route — file-count/size validation happens there, before this is called."""
        import email as stdlib_email
        import email.utils
        from datetime import UTC, datetime

        from ..parsers.email_connector import (
            EmailMessage,
            decode_header_value,
            get_email_body_and_html,
        )
        from .pipeline import _process_emails

        email_messages: list[EmailMessage] = []
        for filename, raw in files:
            try:
                msg = stdlib_email.message_from_bytes(raw)
            except Exception as exc:
                raise EmlParseError(filename, exc) from exc

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
                msg.get("Message-ID") or f"upload-{filename}-{datetime.now(tz=UTC).timestamp()}"
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

        result = _process_emails(email_messages, user_id=user_id, use_llm=True, skip_dedup=True)
        return {
            "emails_processed": result["emails_processed"],
            "flights_created": result["flights_created"],
            "flights_updated": result["flights_updated"],
            "stays_created": result["stays_created"],
        }


sync_service = SyncService()
