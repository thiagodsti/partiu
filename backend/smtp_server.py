"""
Inbound SMTP server — accepts forwarded flight confirmation emails.

Configure via .env:
  SMTP_SERVER_ENABLED=true
  SMTP_SERVER_PORT=2525          # port to listen on (use 2525 to avoid needing root)
  SMTP_ALLOWED_SENDERS=you@gmail.com,partner@gmail.com   # comma-separated allowlist

Per-user recipient addresses are stored in the users table (smtp_recipient_address).
If SMTP_ALLOWED_SENDERS is empty, any sender is accepted (less secure).
"""

import email as email_lib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header as _decode_header
from email.utils import parsedate_to_datetime

from aiosmtpd.controller import Controller

logger = logging.getLogger(__name__)

_controller: Controller | None = None


def _decode_mime_header(value: str) -> str:
    """Decode a potentially RFC-2047-encoded email header value."""
    if not value:
        return ''
    parts = []
    for chunk, enc in _decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or 'utf-8', errors='replace'))
        else:
            parts.append(chunk)
    return ''.join(parts)


def _find_user_by_recipient(address: str) -> dict | None:
    """Look up a user whose smtp_recipient_address matches the given address."""
    from .database import db_conn
    addr_lower = address.lower().strip()
    with db_conn() as conn:
        row = conn.execute(
            'SELECT id, smtp_recipient_address FROM users WHERE lower(smtp_recipient_address) = ?',
            (addr_lower,)
        ).fetchone()
    return dict(row) if row else None


class _FlightEmailHandler:
    """aiosmtpd handler: validates sender/recipient then routes through the parsing pipeline."""

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        from .config import settings

        # First check per-user smtp_recipient_address in DB
        user = _find_user_by_recipient(address)
        if user:
            envelope.rcpt_tos.append(address)
            # Store user_id on envelope for use in handle_DATA
            if not hasattr(envelope, 'smtp_user_id'):
                envelope.smtp_user_id = user['id']
            return '250 OK'

        # Fall back to global SMTP_RECIPIENT_ADDRESS from config
        expected = (settings.SMTP_RECIPIENT_ADDRESS or '').lower().strip()
        if expected and address.lower().strip() != expected:
            logger.debug('SMTP: rejected mail to unknown recipient %s', address)
            return '550 5.1.1 Recipient not accepted'

        # No per-user match and no global recipient configured — reject
        logger.debug('SMTP: rejected mail to unknown recipient %s', address)
        return '550 5.1.1 Recipient not accepted'

    async def handle_DATA(self, server, session, envelope):
        from .config import settings

        sender = (envelope.mail_from or '').lower().strip()
        allowed_raw = (settings.SMTP_ALLOWED_SENDERS or '').strip()
        if allowed_raw:
            allowed = {s.strip().lower() for s in allowed_raw.split(',') if s.strip()}
            if sender not in allowed:
                logger.warning('SMTP: rejected email from unauthorized sender: %s', sender)
                return '550 5.7.1 Sender not authorized'

        user_id = getattr(envelope, 'smtp_user_id', None)

        try:
            raw_msg = email_lib.message_from_bytes(envelope.content)
            _process_raw_message(raw_msg, envelope.mail_from, user_id=user_id)
        except Exception as e:
            logger.error('SMTP: error processing message from %s: %s', envelope.mail_from, e, exc_info=True)

        return '250 Message accepted for delivery'


def _extract_original_sender(raw_msg) -> str | None:
    """
    For forwarded emails, try to find the original airline sender.
    Checks three forwarding styles:
      1. Proper forward: original email attached as message/rfc822 MIME part.
      2. Inline plain-text forward: "From: email@airline.com" in body.
      3. Inline HTML forward (e.g. Tutanota): "From:" and address in separate
         table cells, recovered after html_to_text conversion.
    """
    from .parsers.email_connector import html_to_text

    # Style 1: message/rfc822 attachment
    for part in raw_msg.walk():
        if part.get_content_type() == 'message/rfc822':
            inner = part.get_payload(decode=False)
            if isinstance(inner, list) and inner:
                from_hdr = inner[0].get('From', '')
                if from_hdr:
                    return _decode_mime_header(from_hdr)

    # Styles 2 & 3: scan plain-text and HTML bodies.
    # Collect ALL From: addresses — the LAST one is the deepest/original sender
    # in the forwarding chain (each forward prepends its own From: to the body).
    candidates: list[str] = []

    for part in raw_msg.walk():
        ct = part.get_content_type()
        if ct not in ('text/plain', 'text/html'):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or 'utf-8'
        text = payload.decode(charset, errors='replace')
        if ct == 'text/html':
            text = html_to_text(text)

        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r'^(?:From|De|Von|Fra|Van):\s*(.*)$', line.strip(), re.IGNORECASE)
            if not m:
                continue
            value = m.group(1).strip()
            if '@' in value:
                candidates.append(value)
            else:
                # HTML table case: address may be on next non-empty line(s)
                for next_line in lines[i + 1:i + 4]:
                    next_line = next_line.strip()
                    if re.search(r'\S+@\S+\.\S+', next_line):
                        candidates.append(next_line)
                        break
                    if next_line:
                        break  # non-empty, non-email line — stop looking

    if not candidates:
        return None

    # Return the first candidate that matches a known airline sender pattern
    from .parsers.engine import get_rules
    rules = get_rules()
    for candidate in candidates:
        for rule in rules:
            if re.search(rule.sender_pattern, candidate, re.IGNORECASE):
                return candidate

    return None


def _process_raw_message(raw_msg, sender_address: str, user_id: int | None = None):
    """Convert a raw email.message.Message to an EmailMessage and run it through the pipeline."""
    from .parsers.email_connector import get_email_body_and_html, EmailMessage
    from .sync_job import process_inbound_email

    # Prefer the From header inside the email (original sender) over the SMTP envelope
    # sender. This is critical when emails are forwarded — the envelope sender is the
    # forwarder's address, but the From header has the airline's address that rules match on.
    from_header = _decode_mime_header(raw_msg.get('From', '') or '')
    effective_sender = from_header or sender_address

    # For forwarded emails (FWD:/FW: prefix), try to recover the original airline sender.
    subject_check = _decode_mime_header(raw_msg.get('Subject', '') or '').lower().lstrip()
    if re.match(r'^(fwd?|fw)\s*:', subject_check):
        original = _extract_original_sender(raw_msg)
        if original:
            logger.info('SMTP: forwarded email, original sender extracted: %s → %s', effective_sender, original)
            effective_sender = original

    subject = _decode_mime_header(raw_msg.get('Subject', '') or '')
    message_id = (raw_msg.get('Message-ID') or
                  f'smtp-inbound-{datetime.now(timezone.utc).timestamp()}').strip()

    date = None
    date_str = raw_msg.get('Date', '')
    if date_str:
        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            pass

    body, html_body, pdf_attachments = get_email_body_and_html(raw_msg)

    email_msg = EmailMessage(
        message_id=message_id,
        sender=effective_sender,
        subject=subject,
        body=body,
        date=date,
        html_body=html_body,
        pdf_attachments=pdf_attachments,
    )

    process_inbound_email(email_msg, user_id=user_id)


def start_smtp_server():
    from .config import settings
    global _controller
    if not settings.SMTP_SERVER_ENABLED:
        logger.debug('SMTP server disabled (SMTP_SERVER_ENABLED not set)')
        return
    handler = _FlightEmailHandler()
    _controller = Controller(handler, hostname='0.0.0.0', port=settings.SMTP_SERVER_PORT)
    _controller.start()
    logger.info(
        'SMTP server listening on port %d (allowed=%s)',
        settings.SMTP_SERVER_PORT,
        settings.SMTP_ALLOWED_SENDERS or '*',
    )


def stop_smtp_server():
    global _controller
    if _controller:
        _controller.stop()
        _controller = None
        logger.info('SMTP server stopped')
