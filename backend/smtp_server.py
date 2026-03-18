"""
Inbound SMTP server — accepts forwarded flight confirmation emails.

Configure via .env:
  SMTP_SERVER_ENABLED=true
  SMTP_SERVER_PORT=2525          # port to listen on (use 2525 to avoid needing root)
  SMTP_RECIPIENT_ADDRESS=trips@your-domain.com   # only accept mail to this address
  SMTP_ALLOWED_SENDERS=you@gmail.com,partner@gmail.com   # comma-separated allowlist

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


class _FlightEmailHandler:
    """aiosmtpd handler: validates sender/recipient then routes through the parsing pipeline."""

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        from .config import settings
        expected = (settings.SMTP_RECIPIENT_ADDRESS or '').lower().strip()
        if expected and address.lower().strip() != expected:
            logger.debug('SMTP: rejected mail to unknown recipient %s', address)
            return '550 5.1.1 Recipient not accepted'
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session, envelope):
        from .config import settings

        sender = (envelope.mail_from or '').lower().strip()
        allowed_raw = (settings.SMTP_ALLOWED_SENDERS or '').strip()
        if allowed_raw:
            allowed = {s.strip().lower() for s in allowed_raw.split(',') if s.strip()}
            if sender not in allowed:
                logger.warning('SMTP: rejected email from unauthorized sender: %s', sender)
                return '550 5.7.1 Sender not authorized'

        try:
            raw_msg = email_lib.message_from_bytes(envelope.content)
            _process_raw_message(raw_msg, envelope.mail_from)
        except Exception as e:
            logger.error('SMTP: error processing message from %s: %s', envelope.mail_from, e, exc_info=True)

        return '250 Message accepted for delivery'


def _extract_original_sender(raw_msg) -> str | None:
    """
    For forwarded emails, try to find the original airline sender.
    Checks two forwarding styles:
      1. Proper forward: original email attached as message/rfc822 MIME part.
      2. Inline forward: original headers quoted in the plain-text body.
    """
    # Style 1: message/rfc822 attachment
    for part in raw_msg.walk():
        if part.get_content_type() == 'message/rfc822':
            inner = part.get_payload(decode=False)
            if isinstance(inner, list) and inner:
                from_hdr = inner[0].get('From', '')
                if from_hdr:
                    return _decode_mime_header(from_hdr)

    # Style 2: scan plain-text body for "From: " lines (inline forward)
    for part in raw_msg.walk():
        if part.get_content_type() == 'text/plain':
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or 'utf-8'
            text = payload.decode(charset, errors='replace')
            for line in text.splitlines():
                m = re.match(r'^(?:From|De|Von|Fra|Van):\s*(.+)$', line, re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip()
                    if '@' in candidate:
                        return candidate

    return None


def _process_raw_message(raw_msg, sender_address: str):
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
            logger.debug('SMTP: forwarded email, original sender: %s → %s', effective_sender, original)
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

    process_inbound_email(email_msg)


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
        'SMTP server listening on port %d (recipient=%s, allowed=%s)',
        settings.SMTP_SERVER_PORT,
        settings.SMTP_RECIPIENT_ADDRESS or '*',
        settings.SMTP_ALLOWED_SENDERS or '*',
    )


def stop_smtp_server():
    global _controller
    if _controller:
        _controller.stop()
        _controller = None
        logger.info('SMTP server stopped')
