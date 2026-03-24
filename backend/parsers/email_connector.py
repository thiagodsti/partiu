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
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    """HTML-to-text converter that preserves structure via newlines after block elements."""

    BLOCK_TAGS = frozenset(
        [
            "p",
            "div",
            "br",
            "tr",
            "td",
            "th",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "table",
            "blockquote",
            "pre",
            "section",
            "article",
            "header",
            "footer",
        ]
    )

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_data(self, data):
        self._pieces.append(data)

    def get_text(self):
        text = "".join(self._pieces)
        # Collapse horizontal whitespace (preserve newlines)
        text = re.sub(r"[^\S\n]+", " ", text)
        # Collapse runs of blank lines into at most one blank line
        text = re.sub(r"\n[ \t]*\n", "\n\n", text)
        lines = [line.strip() for line in text.split("\n")]
        # Deduplicate consecutive blank lines
        result: list[str] = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty:
                    result.append("")
                prev_empty = True
            else:
                result.append(line)
                prev_empty = False
        return "\n".join(result).strip()


def html_to_text(html_content: str) -> str:
    """Convert HTML to structured plain text, preserving block-level line breaks."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html_content)
    return extractor.get_text()


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


def get_email_body_and_html(msg) -> tuple[str, str | None, list[bytes]]:
    """
    Extract text, raw HTML, and raw PDF bytes from an email message.
    Returns (text_body, raw_html, pdf_bytes_list).
    text_body combines plain-text, HTML-to-text, and PDF attachment text.
    raw_html is the original HTML content (for BS4 parsing), or None.
    pdf_bytes_list contains raw bytes of any PDF attachments found.
    """
    plain_body = ""
    html_text = ""
    raw_html = None
    pdf_texts = []
    pdf_bytes_list: list[bytes] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and not plain_body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    plain_body = payload.decode(charset, errors="replace")
            elif content_type == "text/html" and raw_html is None:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    raw_html = payload.decode(charset, errors="replace")
                    html_text = html_to_text(raw_html)
            elif content_type == "application/pdf":
                payload = part.get_payload(decode=True)
                if payload:
                    pdf_bytes_list.append(payload)
                    pdf_text = _extract_text_from_pdf(payload)
                    if pdf_text:
                        pdf_texts.append(pdf_text)
                        logger.info("Extracted %d chars from PDF attachment", len(pdf_text))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            if msg.get_content_type() == "text/html":
                raw_html = payload.decode(charset, errors="replace")
                html_text = html_to_text(raw_html)
            else:
                plain_body = payload.decode(charset, errors="replace")

    # Combine text parts for regex fallback (includes PDF text)
    parts = []
    if plain_body:
        parts.append(plain_body.strip())
    if html_text:
        parts.append(html_text.strip())
    if pdf_texts:
        parts.extend(pdf_texts)
    text_body = "\n\n".join(parts) if parts else ""

    return text_body, raw_html, pdf_bytes_list


def get_email_body(msg) -> str:
    """Extract text from an email message (backward-compatible wrapper)."""
    text_body, _, _ = get_email_body_and_html(msg)
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
    ):
        self.message_id = message_id
        self.sender = sender
        self.subject = subject
        self.body = body
        self.date = date
        self.html_body = html_body
        self.pdf_attachments: list[bytes] = pdf_attachments or []
        self.raw_eml: bytes | None = raw_eml

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
    r'\b(?:itinerar|e-?ticket|boarding|reserv|booking\s*confirm|'
    r'confirmation|check-?in|flight\s*confirm|viagem|voo|'
    r'[A-Z]{2}\d{3,4})\b',
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
    max_results: int = 200,
) -> ImapFetchResult:
    """
    Fetch emails from an IMAP server, filtering by sender patterns OR flight keywords.

    Returns an ImapFetchResult — never raises; check .success and .error on the result.

    Args:
        sender_patterns: List of regex patterns to match against From header.
            Emails matching these are always fetched (known airlines).
            Emails NOT matching are also fetched if their subject contains
            flight-like keywords (catches unknown/new airlines).
        since_date: Only fetch emails after this date.
        max_results: Maximum number of emails to return.
    """
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
        msg_ids = msg_ids[-max_results:]
        msg_ids.reverse()

        for msg_id in msg_ids:
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

                body, raw_html, pdf_bytes_list = get_email_body_and_html(msg)

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
                    )
                )
            except Exception as e:
                logger.warning("Error processing email %s: %s", msg_id, e)
                continue

        conn.logout()
    except Exception as e:
        err = f"IMAP connection error: {e}"
        logger.error(err)
        return ImapFetchResult(success=False, emails=[], error=err)

    return ImapFetchResult(success=True, emails=messages)
