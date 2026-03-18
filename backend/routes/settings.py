"""
Settings routes — read/write Gmail credentials and app configuration.
Per-user settings stored in users table. Global settings stored in global_settings table.
"""

import imaplib
import ipaddress
import socket

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..database import db_conn, db_write, get_global_setting, set_global_setting


def _validate_imap_host(host: str):
    """Reject private/loopback addresses to prevent SSRF."""
    host = host.strip().lower()
    if not host:
        raise HTTPException(400, "IMAP host cannot be empty")
    # Block obvious internal names
    if host in ("localhost", "localhost.localdomain"):
        raise HTTPException(400, "IMAP host cannot be a local address")
    # Try to resolve and check if it's a private/loopback IP
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
                raise HTTPException(400, "IMAP host cannot be a private or local address")
    except HTTPException:
        raise
    except Exception:
        # DNS resolution failed — still allow it (offline/dev environments)
        pass

router = APIRouter(prefix='/api/settings', tags=['settings'])


@router.get('')
def get_settings(user: dict = Depends(get_current_user)):
    """Return current settings (password masked). Per-user IMAP + global config for admins."""
    response = {
        'gmail_address': user.get('gmail_address') or '',
        'gmail_app_password_set': bool(user.get('gmail_app_password')),
        'imap_host': user.get('imap_host') or 'imap.gmail.com',
        'imap_port': user.get('imap_port') or 993,
        'sync_interval_minutes': int(get_global_setting('sync_interval_minutes', '10')),
        'max_emails_per_sync': int(get_global_setting('max_emails_per_sync', '200')),
        'first_sync_days': int(get_global_setting('first_sync_days', '90')),
        # SMTP server status — needed by all users to show/hide forwarding section
        'smtp_server_enabled': get_global_setting('smtp_server_enabled', 'false') == 'true',
        'smtp_domain': get_global_setting('smtp_domain', ''),
        # Per-user forwarding config
        'smtp_recipient_address': user.get('smtp_recipient_address') or '',
        'smtp_allowed_senders': user.get('smtp_allowed_senders') or '',
    }

    # Admin-only server config
    if user.get('is_admin'):
        response['smtp_server_port'] = int(get_global_setting('smtp_server_port', '2525'))

    return response


class SettingsUpdate(BaseModel):
    # Per-user settings
    gmail_address: str | None = None
    gmail_app_password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    smtp_recipient_address: str | None = None
    smtp_allowed_senders: str | None = None
    # Global settings (admin only)
    sync_interval_minutes: int | None = None
    max_emails_per_sync: int | None = None
    first_sync_days: int | None = None
    smtp_server_enabled: bool | None = None
    smtp_server_port: int | None = None
    smtp_domain: str | None = None


@router.post('')
def update_settings(body: SettingsUpdate, user: dict = Depends(get_current_user)):
    """
    Update settings.
    Per-user settings are stored in the users table.
    Global settings are stored in the global_settings table (admin only).
    """
    # Per-user settings — stored in users table
    user_updates = {}
    if body.gmail_address is not None:
        user_updates['gmail_address'] = body.gmail_address
    if body.gmail_app_password is not None:
        user_updates['gmail_app_password'] = body.gmail_app_password
    if body.imap_host is not None:
        _validate_imap_host(body.imap_host)
        user_updates['imap_host'] = body.imap_host.strip()
    if body.imap_port is not None:
        user_updates['imap_port'] = body.imap_port
    if body.smtp_recipient_address is not None:
        recipient = body.smtp_recipient_address.strip()
        if not recipient:
            smtp_domain = get_global_setting('smtp_domain', '')
            if smtp_domain:
                recipient = f"{user['username']}@{smtp_domain}"
        if recipient:
            with db_conn() as conn:
                conflict = conn.execute(
                    'SELECT id FROM users WHERE lower(smtp_recipient_address) = lower(?) AND id != ?',
                    (recipient, user['id'])
                ).fetchone()
            if conflict:
                raise HTTPException(status_code=409, detail=f'"{recipient}" is already in use by another user')
        user_updates['smtp_recipient_address'] = recipient
    if body.smtp_allowed_senders is not None:
        user_updates['smtp_allowed_senders'] = body.smtp_allowed_senders

    if user_updates:
        set_clause = ', '.join(f'{k} = ?' for k in user_updates)
        with db_write() as conn:
            conn.execute(
                f'UPDATE users SET {set_clause} WHERE id = ?',
                list(user_updates.values()) + [user['id']]
            )

    # Global settings — require admin
    has_global = (
        body.sync_interval_minutes is not None or
        body.max_emails_per_sync is not None or
        body.first_sync_days is not None or
        body.smtp_server_enabled is not None or
        body.smtp_server_port is not None or
        body.smtp_domain is not None
    )
    if has_global:
        if not user.get('is_admin'):
            raise HTTPException(status_code=403, detail='Admin access required for global settings')
        if body.sync_interval_minutes is not None:
            set_global_setting('sync_interval_minutes', str(body.sync_interval_minutes))
        if body.max_emails_per_sync is not None:
            set_global_setting('max_emails_per_sync', str(body.max_emails_per_sync))
        if body.first_sync_days is not None:
            set_global_setting('first_sync_days', str(body.first_sync_days))
        if body.smtp_server_enabled is not None:
            set_global_setting('smtp_server_enabled', 'true' if body.smtp_server_enabled else 'false')
        if body.smtp_server_port is not None:
            set_global_setting('smtp_server_port', str(body.smtp_server_port))
        if body.smtp_domain is not None:
            set_global_setting('smtp_domain', body.smtp_domain)

    return {'ok': True, 'message': 'Settings saved'}


class TestImapRequest(BaseModel):
    imap_host: str | None = None
    imap_port: int | None = None
    gmail_address: str | None = None
    gmail_app_password: str | None = None


@router.post('/test-imap')
def test_imap(body: TestImapRequest, user: dict = Depends(get_current_user)):
    """Try connecting and authenticating to the IMAP server with the given (or stored) credentials."""
    host = (body.imap_host or user.get('imap_host') or 'imap.gmail.com').strip()
    port = body.imap_port or user.get('imap_port') or 993
    address = body.gmail_address or user.get('gmail_address') or ''
    password = body.gmail_app_password or user.get('gmail_app_password') or ''

    if not address:
        raise HTTPException(400, 'Email address is required')
    if not password:
        raise HTTPException(400, 'Password is required — save your settings first or enter it above')

    _validate_imap_host(host)

    try:
        imap = imaplib.IMAP4_SSL(host, port, timeout=10)
        imap.login(address, password)
        imap.logout()
    except imaplib.IMAP4.error as e:
        raise HTTPException(400, f'Authentication failed: {e}')
    except OSError as e:
        raise HTTPException(400, f'Could not connect to {host}:{port} — {e}')
    except Exception as e:
        raise HTTPException(400, f'Connection error: {e}')

    return {'ok': True, 'message': f'Connected to {host}:{port} successfully'}


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
