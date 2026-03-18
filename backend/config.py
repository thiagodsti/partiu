"""
Application settings loaded from environment variables / .env file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of backend/)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / '.env')


class Settings:
    GMAIL_ADDRESS: str = os.getenv('GMAIL_ADDRESS', '')
    GMAIL_APP_PASSWORD: str = os.getenv('GMAIL_APP_PASSWORD', '')
    DB_PATH: str = os.getenv('DB_PATH', str(_ROOT / 'data' / 'tripit.db'))
    IMAP_HOST: str = os.getenv('IMAP_HOST', 'imap.gmail.com')
    IMAP_PORT: int = int(os.getenv('IMAP_PORT', '993'))
    SYNC_INTERVAL_MINUTES: int = int(os.getenv('SYNC_INTERVAL_MINUTES', '10'))
    MAX_EMAILS_PER_SYNC: int = int(os.getenv('MAX_EMAILS_PER_SYNC', '200'))
    FIRST_SYNC_DAYS: int = int(os.getenv('FIRST_SYNC_DAYS', '90'))
    DISABLE_SCHEDULER: bool = os.getenv('DISABLE_SCHEDULER', 'false').lower() == 'true'
    AVIATIONSTACK_API_KEY: str = os.getenv('AVIATIONSTACK_API_KEY', '')
    # Auth
    SECRET_KEY: str = os.getenv('SECRET_KEY', '')
    SESSION_MAX_AGE_DAYS: int = int(os.getenv('SESSION_MAX_AGE_DAYS', '30'))


settings = Settings()
