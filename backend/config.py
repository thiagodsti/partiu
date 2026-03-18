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
    DB_PATH: str = os.getenv('DB_PATH', str(_ROOT / 'data' / 'tripit.db'))
    DISABLE_SCHEDULER: bool = os.getenv('DISABLE_SCHEDULER', 'false').lower() == 'true'
    AVIATIONSTACK_API_KEY: str = os.getenv('AVIATIONSTACK_API_KEY', '')
    # Auth
    SECRET_KEY: str = os.getenv('SECRET_KEY', '')
    SESSION_MAX_AGE_DAYS: int = int(os.getenv('SESSION_MAX_AGE_DAYS', '30'))


settings = Settings()
