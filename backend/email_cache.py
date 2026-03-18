"""
Local email cache — saves fetched EmailMessage objects to a JSON file so
development/testing can replay them without hitting Gmail every time.
PDF attachments are stored as base64 so they can be re-extracted later.
"""
import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from .config import settings
from .parsers.email_connector import EmailMessage, _extract_text_from_pdf

logger = logging.getLogger(__name__)


def _cache_path() -> Path:
    return Path(settings.DB_PATH).parent / 'email_cache.json'


def save_emails(emails: list[EmailMessage]) -> None:
    """Serialise a list of EmailMessage objects to the local cache file."""
    data = []
    for em in emails:
        data.append({
            'message_id': em.message_id,
            'sender': em.sender,
            'subject': em.subject,
            'body': em.body,
            'html_body': em.html_body,
            'date': em.date.isoformat() if em.date else None,
            'pdf_attachments': [
                base64.b64encode(b).decode('ascii') for b in (em.pdf_attachments or [])
            ],
        })
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d emails to cache at %s", len(data), path)


def load_emails() -> list[EmailMessage]:
    """Load EmailMessage objects from the local cache file."""
    path = _cache_path()
    if not path.exists():
        logger.warning("Email cache not found at %s — run a full sync first", path)
        return []
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    emails = []
    for item in data:
        date = None
        if item.get('date'):
            try:
                date = datetime.fromisoformat(item['date'])
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
            except ValueError:
                pass
        # Load PDF attachments from base64
        pdf_attachments = []
        for b64 in item.get('pdf_attachments') or []:
            try:
                pdf_attachments.append(base64.b64decode(b64))
            except Exception:
                pass

        # Re-extract PDF text and append to body if it's missing
        # (handles emails cached before pdfplumber was installed)
        body = item['body']
        if pdf_attachments and body:
            for pdf_bytes in pdf_attachments:
                pdf_text = _extract_text_from_pdf(pdf_bytes)
                if pdf_text and pdf_text[:50] not in body:
                    body = body + '\n\n' + pdf_text
                    logger.info("Re-extracted %d chars from cached PDF", len(pdf_text))

        emails.append(EmailMessage(
            message_id=item['message_id'],
            sender=item['sender'],
            subject=item['subject'],
            body=body,
            date=date,
            html_body=item.get('html_body'),
            pdf_attachments=pdf_attachments,
        ))
    logger.info("Loaded %d emails from cache at %s", len(emails), path)
    return emails


def cache_exists() -> bool:
    return _cache_path().exists()
