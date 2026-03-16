"""
Settings routes — read/write Gmail credentials and app configuration.
"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix='/api/settings', tags=['settings'])

_ENV_PATH = Path(__file__).parent.parent.parent / '.env'


def _read_env() -> dict:
    """Read current .env file into a dict."""
    env = {}
    if _ENV_PATH.exists():
        with open(_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _write_env(env: dict):
    """Write env dict to .env file."""
    lines = []
    for key, value in env.items():
        lines.append(f'{key}={value}\n')
    with open(_ENV_PATH, 'w') as f:
        f.writelines(lines)


@router.get('')
def get_settings():
    """Return current settings (password masked)."""
    from ..config import settings
    return {
        'gmail_address': settings.GMAIL_ADDRESS,
        'gmail_app_password_set': bool(settings.GMAIL_APP_PASSWORD),
        'imap_host': settings.IMAP_HOST,
        'imap_port': settings.IMAP_PORT,
        'sync_interval_minutes': settings.SYNC_INTERVAL_MINUTES,
        'max_emails_per_sync': settings.MAX_EMAILS_PER_SYNC,
        'first_sync_days': settings.FIRST_SYNC_DAYS,
        'smtp_server_enabled': settings.SMTP_SERVER_ENABLED,
        'smtp_server_port': settings.SMTP_SERVER_PORT,
        'smtp_recipient_address': settings.SMTP_RECIPIENT_ADDRESS,
        'smtp_allowed_senders': settings.SMTP_ALLOWED_SENDERS,
    }


class SettingsUpdate(BaseModel):
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    sync_interval_minutes: int | None = None
    smtp_server_enabled: bool | None = None
    smtp_server_port: int | None = None
    smtp_recipient_address: str | None = None
    smtp_allowed_senders: str | None = None


@router.post('')
def update_settings(body: SettingsUpdate):
    """
    Update Gmail credentials and settings.
    Writes to .env file and reloads settings.
    """
    env = _read_env()

    if body.gmail_address is not None:
        env['GMAIL_ADDRESS'] = body.gmail_address
    if body.gmail_app_password is not None:
        env['GMAIL_APP_PASSWORD'] = body.gmail_app_password
    if body.imap_host is not None:
        env['IMAP_HOST'] = body.imap_host
    if body.imap_port is not None:
        env['IMAP_PORT'] = str(body.imap_port)
    if body.sync_interval_minutes is not None:
        env['SYNC_INTERVAL_MINUTES'] = str(body.sync_interval_minutes)

    if body.smtp_server_enabled is not None:
        env['SMTP_SERVER_ENABLED'] = 'true' if body.smtp_server_enabled else 'false'
    if body.smtp_server_port is not None:
        env['SMTP_SERVER_PORT'] = str(body.smtp_server_port)
    if body.smtp_recipient_address is not None:
        env['SMTP_RECIPIENT_ADDRESS'] = body.smtp_recipient_address
    if body.smtp_allowed_senders is not None:
        env['SMTP_ALLOWED_SENDERS'] = body.smtp_allowed_senders

    try:
        _write_env(env)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save settings: {e}')

    # Reload in-process settings
    from ..config import settings
    if body.gmail_address is not None:
        settings.GMAIL_ADDRESS = body.gmail_address
    if body.gmail_app_password is not None:
        settings.GMAIL_APP_PASSWORD = body.gmail_app_password
    if body.imap_host is not None:
        settings.IMAP_HOST = body.imap_host
    if body.imap_port is not None:
        settings.IMAP_PORT = body.imap_port
    if body.sync_interval_minutes is not None:
        settings.SYNC_INTERVAL_MINUTES = body.sync_interval_minutes
    if body.smtp_server_enabled is not None:
        settings.SMTP_SERVER_ENABLED = body.smtp_server_enabled
    if body.smtp_server_port is not None:
        settings.SMTP_SERVER_PORT = body.smtp_server_port
    if body.smtp_recipient_address is not None:
        settings.SMTP_RECIPIENT_ADDRESS = body.smtp_recipient_address
    if body.smtp_allowed_senders is not None:
        settings.SMTP_ALLOWED_SENDERS = body.smtp_allowed_senders

    return {'ok': True, 'message': 'Settings saved'}


@router.get('/airports/count')
def get_airport_count():
    """Return the number of airports loaded in the database."""
    from ..database import db_conn
    with db_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM airports').fetchone()[0]
    return {'count': count}


@router.post('/airports/reload')
def reload_airports():
    """Re-load airports from data/airports.csv."""
    from ..database import load_airports_if_empty, db_write
    with db_write() as conn:
        conn.execute('DELETE FROM airports')
    load_airports_if_empty()
    from ..database import db_conn
    with db_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM airports').fetchone()[0]
    return {'ok': True, 'count': count}
