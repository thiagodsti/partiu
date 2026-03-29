"""
Application settings loaded from environment variables / .env file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of backend/)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")


class Settings:
    DB_PATH: str = os.getenv("DB_PATH", str(_ROOT / "data" / "tripit.db"))
    DISABLE_SCHEDULER: bool = os.getenv("DISABLE_SCHEDULER", "false").lower() == "true"
    AVIATIONSTACK_API_KEY: str = os.getenv("AVIATIONSTACK_API_KEY", "")
    # Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    SESSION_MAX_AGE_DAYS: int = int(os.getenv("SESSION_MAX_AGE_DAYS", "30"))
    # Audit log
    AUDIT_LOG_MAX_MB: int = int(os.getenv("AUDIT_LOG_MAX_MB", "10"))
    # Email cache
    EMAIL_CACHE_MAX_ENTRIES: int = int(os.getenv("EMAIL_CACHE_MAX_ENTRIES", "500"))
    # Web Push: override VAPID keys via env vars (optional — auto-generated on first run otherwise)
    VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_SUBJECT: str = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    # LLM fallback (optional — requires a running Ollama instance)
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "180"))


settings = Settings()
