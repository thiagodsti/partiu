"""
Settings routes — read/write Gmail credentials and app configuration.
Per-user IMAP settings stored in users table. Global settings require admin.
"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..database import db_conn, db_write

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
def get_settings(user: dict = Depends(get_current_user)):
    """Return current settings (password masked). Per-user IMAP + global config for admins."""
    from ..config import settings

    # Per-user IMAP settings — no global fallback, each user configures their own
    gmail_address = user.get('gmail_address') or ''
    gmail_app_password_set = bool(user.get('gmail_app_password'))
    imap_host = user.get('imap_host') or settings.IMAP_HOST
    imap_port = user.get('imap_port') or settings.IMAP_PORT

    response = {
        'gmail_address': gmail_address,
        'gmail_app_password_set': gmail_app_password_set,
        'imap_host': imap_host,
        'imap_port': imap_port,
        'sync_interval_minutes': settings.SYNC_INTERVAL_MINUTES,
        'max_emails_per_sync': settings.MAX_EMAILS_PER_SYNC,
        'first_sync_days': settings.FIRST_SYNC_DAYS,
    }

    # Global/admin-only settings
    if user.get('is_admin'):
        response.update({
            'smtp_server_enabled': settings.SMTP_SERVER_ENABLED,
            'smtp_server_port': settings.SMTP_SERVER_PORT,
            'smtp_recipient_address': settings.SMTP_RECIPIENT_ADDRESS,
            'smtp_allowed_senders': settings.SMTP_ALLOWED_SENDERS,
        })

    return response


class SettingsUpdate(BaseModel):
    # Per-user IMAP settings
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    # Global settings (admin only)
    sync_interval_minutes: int | None = None
    smtp_server_enabled: bool | None = None
    smtp_server_port: int | None = None
    smtp_recipient_address: str | None = None
    smtp_allowed_senders: str | None = None


@router.post('')
def update_settings(body: SettingsUpdate, user: dict = Depends(get_current_user)):
    """
    Update settings.
    Per-user IMAP settings are stored in the users table.
    Global settings (SMTP, scheduler) are written to .env and require admin.
    """
    from ..config import settings as app_settings

    # Per-user IMAP settings — stored in users table
    user_updates = {}
    if body.gmail_address is not None:
        user_updates['gmail_address'] = body.gmail_address
    if body.gmail_app_password is not None:
        user_updates['gmail_app_password'] = body.gmail_app_password
    if body.imap_host is not None:
        user_updates['imap_host'] = body.imap_host
    if body.imap_port is not None:
        user_updates['imap_port'] = body.imap_port

    if user_updates:
        set_clause = ', '.join(f'{k} = ?' for k in user_updates)
        with db_write() as conn:
            conn.execute(
                f'UPDATE users SET {set_clause} WHERE id = ?',
                list(user_updates.values()) + [user['id']]
            )

    # Global settings — require admin
    global_updates = {}
    if body.sync_interval_minutes is not None:
        global_updates['SYNC_INTERVAL_MINUTES'] = str(body.sync_interval_minutes)
    if body.smtp_server_enabled is not None:
        global_updates['SMTP_SERVER_ENABLED'] = 'true' if body.smtp_server_enabled else 'false'
    if body.smtp_server_port is not None:
        global_updates['SMTP_SERVER_PORT'] = str(body.smtp_server_port)
    if body.smtp_recipient_address is not None:
        global_updates['SMTP_RECIPIENT_ADDRESS'] = body.smtp_recipient_address
    if body.smtp_allowed_senders is not None:
        global_updates['SMTP_ALLOWED_SENDERS'] = body.smtp_allowed_senders

    if global_updates:
        if not user.get('is_admin'):
            raise HTTPException(status_code=403, detail='Admin access required for global settings')

        env = _read_env()
        env.update(global_updates)
        try:
            _write_env(env)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'Failed to save settings: {e}')

        # Reload in-process settings
        if body.sync_interval_minutes is not None:
            app_settings.SYNC_INTERVAL_MINUTES = body.sync_interval_minutes
        if body.smtp_server_enabled is not None:
            app_settings.SMTP_SERVER_ENABLED = body.smtp_server_enabled
        if body.smtp_server_port is not None:
            app_settings.SMTP_SERVER_PORT = body.smtp_server_port
        if body.smtp_recipient_address is not None:
            app_settings.SMTP_RECIPIENT_ADDRESS = body.smtp_recipient_address
        if body.smtp_allowed_senders is not None:
            app_settings.SMTP_ALLOWED_SENDERS = body.smtp_allowed_senders

    return {'ok': True, 'message': 'Settings saved'}


@router.get('/airports/count')
def get_airport_count(user: dict = Depends(get_current_user)):
    """Return the number of airports loaded in the database."""
    with db_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM airports').fetchone()[0]
    return {'count': count}


@router.post('/airports/reload')
def reload_airports(user: dict = Depends(require_admin)):
    """Re-load airports from data/airports.csv. Admin only."""
    from ..database import load_airports_if_empty
    with db_write() as conn:
        conn.execute('DELETE FROM airports')
    load_airports_if_empty()
    with db_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM airports').fetchone()[0]
    return {'ok': True, 'count': count}
