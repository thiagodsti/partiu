"""
Email connection utilities for fetching flight-related emails from various providers.
Supports IMAP (Gmail, generic).

Adapted from AdventureLog — Django dependencies removed.
"""

import email
import email.header
import email.utils
import imaplib
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def html_to_text(html_content: str) -> str:
    """Convert HTML to clean plain text. Delegates to parsers.shared.html_to_text."""
    from .shared import html_to_text as _html_to_text

    return _html_to_text(html_content)


def decode_header_value(raw: str) -> str:
    """Decode an RFC-2047 encoded header value into a Python string."""
    parts = email.header.decode_header(raw)
    decoded_parts = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from a PDF attachment (requires pdfplumber)."""
    import io

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n".join(pages)
    except ImportError:
        logger.debug("pdfplumber not installed — skipping PDF extraction")
        return ""
    except Exception as e:
        logger.warning("Failed to extract PDF text: %s", e)
        return ""


def _parse_ics_text(ics: str) -> str:
    """Convert an ICS calendar attachment to a one-line flight summary."""
    summary = description = dtstart = dtend = ""
    for line in ics.splitlines():
        line = line.strip()
        if line.startswith("SUMMARY:"):
            summary = line[8:]
        elif line.startswith("DESCRIPTION:"):
            description = line[12:].replace("\\n", " ").replace("\\,", ",")
        elif line.startswith("DTSTART:"):
            dtstart = line[8:]
        elif line.startswith("DTEND:"):
            dtend = line[6:]
    parts = []
    if summary:
        parts.append(f"Flight: {summary}")
    if description:
        parts.append(f"Details: {description.split('http')[0].strip()}")
    if dtstart:
        parts.append(f"Departure (UTC): {dtstart}")
    if dtend:
        parts.append(f"Arrival (UTC): {dtend}")
    return "\n".join(parts)


def get_email_body_and_html(msg) -> tuple[str, str | None, list[bytes], list[str]]:
    """
    Extract text, raw HTML, PDF bytes, and ICS calendar texts from an email message.
    Returns (text_body, raw_html, pdf_bytes_list, ics_texts).
    text_body prefers HTML-derived text over plain text (plain text in airline emails
    is often just tracking URLs). ICS attachments are always appended when present.
    raw_html is the original HTML content (for BS4 parsing), or None.
    pdf_bytes_list contains raw bytes of any PDF attachments found.
    ics_texts contains parsed summaries of any ICS/calendar attachments.
    """
    plain_body = ""
    html_text = ""
    raw_html = None
    pdf_texts = []
    pdf_bytes_list: list[bytes] = []
    ics_texts: list[str] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")

        if content_type in ("application/ics", "text/calendar"):
            ics_texts.append(_parse_ics_text(decoded))
        elif content_type == "text/html" and raw_html is None:
            raw_html = decoded
            html_text = html_to_text(raw_html)
        elif content_type == "application/pdf":
            pdf_bytes_list.append(payload)
            pdf_text = _extract_text_from_pdf(payload)
            if pdf_text:
                pdf_texts.append(pdf_text)
                logger.info("Extracted %d chars from PDF attachment", len(pdf_text))
        elif content_type == "text/plain" and not plain_body:
            # Some airlines mislabel HTML content as text/plain — detect and skip
            if not decoded.lstrip().startswith(("<", "<!")):
                plain_body = decoded

    # Prefer HTML-derived text — airline plain text is often just tracking URLs.
    # Fall back to plain text only when no HTML is available.
    body_source = html_text.strip() if html_text else plain_body.strip()

    parts = [body_source] if body_source else []
    if pdf_texts:
        parts.extend(pdf_texts)
    if ics_texts:
        parts.append("--- CALENDAR ATTACHMENTS ---\n" + "\n\n".join(ics_texts))
    text_body = "\n\n".join(parts)

    return text_body, raw_html, pdf_bytes_list, ics_texts


def get_email_body(msg) -> str:
    """Extract text from an email message (backward-compatible wrapper)."""
    text_body, _, _, _ = get_email_body_and_html(msg)
    return text_body


class EmailMessage:
    """Lightweight container for a fetched email."""

    def __init__(
        self,
        message_id: str,
        sender: str,
        subject: str,
        body: str,
        date: datetime | None,
        html_body: str | None = None,
        pdf_attachments: list[bytes] | None = None,
        raw_eml: bytes | None = None,
        ics_texts: list[str] | None = None,
    ):
        self.message_id = message_id
        self.sender = sender
        self.subject = subject
        self.body = body
        self.date = date
        self.html_body = html_body
        self.pdf_attachments: list[bytes] = pdf_attachments or []
        self.raw_eml: bytes | None = raw_eml
        self.ics_texts: list[str] = ics_texts or []

    def get_pdf_text(self) -> str:
        """Extract text from any stored PDF attachments (requires pdfplumber)."""
        texts = []
        for pdf_bytes in self.pdf_attachments:
            text = _extract_text_from_pdf(pdf_bytes)
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    def __repr__(self):
        return f"<EmailMessage {self.message_id!r} from={self.sender!r} subj={self.subject[:40]!r}>"


class ImapFetchResult:
    """Typed result from fetch_emails_imap — never raises, always returns this."""

    __slots__ = ("success", "emails", "error")

    def __init__(self, success: bool, emails: list["EmailMessage"], error: str | None = None):
        self.success = success
        self.emails = emails
        self.error = error

    def __repr__(self) -> str:
        return f"<ImapFetchResult success={self.success} emails={len(self.emails)} error={self.error!r}>"


def connect_imap(
    host: str, port: int, username: str, password: str, use_ssl: bool = True
) -> imaplib.IMAP4:
    """Connect and authenticate to an IMAP server."""
    if use_ssl:
        conn = imaplib.IMAP4_SSL(host, port)
    else:
        conn = imaplib.IMAP4(host, port)
    conn.login(username, password)
    return conn


# Subject keywords that suggest a flight-related email from any airline.
# Used to catch emails from unknown senders that might contain itinerary data.
_FLIGHT_SUBJECT_KEYWORDS = re.compile(
    r"\b(?:itinerary?|e-?ticket|boarding|reservat\w*|booking\s*confirm\w*|"
    r"confirmation|check-?in|flight\s*confirm\w*|viagem|voo)\b"
    r"|\b[A-Z]{2}\d{3,4}\b",
    re.IGNORECASE,
)


def _matches_flight_filter(
    sender: str,
    subject: str,
    sender_patterns: list[str] | None,
) -> bool:
    """
    Return True if the email should be fetched for flight parsing.

    Accepts if:
      - sender matches any known airline sender_pattern, OR
      - subject contains a flight-like keyword (catches unknown airlines)
    """
    if sender_patterns:
        for pattern in sender_patterns:
            if re.search(pattern, sender, re.IGNORECASE):
                return True
    return bool(_FLIGHT_SUBJECT_KEYWORDS.search(subject))


def fetch_emails_imap(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool = True,
    sender_patterns: list[str] | None = None,
    since_date: datetime | None = None,
    folder: str = "INBOX",
    progress_callback: object = None,
) -> ImapFetchResult:
    """
    Fetch emails from an IMAP server, filtering by sender patterns OR flight keywords.

    progress_callback: optional callable(fetched, total) called as emails are downloaded.

    Returns an ImapFetchResult — never raises; check .success and .error on the result.

    Args:
        sender_patterns: List of regex patterns to match against From header.
            Emails matching these are always fetched (known airlines).
            Emails NOT matching are also fetched if their subject contains
            flight-like keywords (catches unknown/new airlines).
        since_date: Only fetch emails after this date.
    """
    # Reconnect every BATCH_SIZE fetches to avoid SSL session timeouts on large mailboxes
    BATCH_SIZE = 100

    messages: list[EmailMessage] = []
    try:
        conn = connect_imap(host, port, username, password, use_ssl)
        conn.select(folder, readonly=True)

        # Build IMAP search criteria (date filter only — Python handles the rest)
        search_criteria = []
        if since_date:
            date_str = since_date.strftime("%d-%b-%Y")
            search_criteria.append(f"SINCE {date_str}")

        criteria_str = " ".join(search_criteria) if search_criteria else "ALL"
        status, data = conn.search(None, criteria_str)  # noqa: S608
        if status != "OK":
            err = f"IMAP search failed with status: {status}"
            logger.error(err)
            return ImapFetchResult(success=False, emails=[], error=err)

        msg_ids = data[0].split()
        # Process most recent first
        msg_ids.reverse()
        conn.logout()

        # Report total as soon as we know it
        if progress_callback and msg_ids:
            try:
                progress_callback(0, len(msg_ids))  # type: ignore[operator]
            except Exception:
                pass
    except Exception as e:
        err = f"IMAP connection error: {e}"
        logger.error(err)
        return ImapFetchResult(success=False, emails=[], error=err)

    total = len(msg_ids)
    fetched = 0

    # Fetch emails in batches, reconnecting between each to avoid SSL timeouts
    for batch_start in range(0, total, BATCH_SIZE):
        batch = msg_ids[batch_start : batch_start + BATCH_SIZE]
        try:
            conn = connect_imap(host, port, username, password, use_ssl)
            conn.select(folder, readonly=True)
            for msg_id in batch:
                try:
                    status, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue
                    item = msg_data[0]
                    if not isinstance(item, (tuple, list)):
                        continue
                    raw_email: bytes = item[1]
                    msg = email.message_from_bytes(raw_email)

                    sender = decode_header_value(msg.get("From", ""))
                    subject = decode_header_value(msg.get("Subject", ""))
                    message_id = msg.get("Message-ID", f"imap-{msg_id.decode()}")

                    # Filter: known sender pattern OR flight-like subject keyword
                    if not _matches_flight_filter(sender, subject, sender_patterns):
                        continue

                    body, raw_html, pdf_bytes_list, ics_texts = get_email_body_and_html(msg)

                    # Parse date
                    date_str = msg.get("Date", "")
                    msg_date = None
                    if date_str:
                        try:
                            msg_date = email.utils.parsedate_to_datetime(date_str)
                        except Exception:
                            pass

                    messages.append(
                        EmailMessage(
                            message_id=message_id,
                            sender=sender,
                            subject=subject,
                            body=body,
                            date=msg_date,
                            html_body=raw_html,
                            pdf_attachments=pdf_bytes_list,
                            raw_eml=raw_email,
                            ics_texts=ics_texts,
                        )
                    )
                except Exception as e:
                    logger.warning("Error processing email %s: %s", msg_id, e)
                finally:
                    fetched += 1
                    if progress_callback:
                        try:
                            progress_callback(fetched, total)  # type: ignore[operator]
                        except Exception:
                            pass
            conn.logout()
        except Exception as e:
            err = f"IMAP connection error: {e}"
            logger.error(err)
            return ImapFetchResult(success=False, emails=[], error=err)

    return ImapFetchResult(success=True, emails=messages)
