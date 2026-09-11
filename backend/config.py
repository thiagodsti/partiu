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
    DB_PATH: str = os.getenv("DB_PATH", str(_ROOT / "data" / "partiu.db"))
    DISABLE_SCHEDULER: bool = os.getenv("DISABLE_SCHEDULER", "false").lower() == "true"
    AVIATIONSTACK_API_KEY: str = os.getenv("AVIATIONSTACK_API_KEY", "")
    # Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    SESSION_MAX_AGE_DAYS: int = int(os.getenv("SESSION_MAX_AGE_DAYS", "30"))
    # Audit log
    AUDIT_LOG_MAX_MB: int = int(os.getenv("AUDIT_LOG_MAX_MB", "10"))
    # Web Push: override VAPID keys via env vars (optional — auto-generated on first run otherwise)
    VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_SUBJECT: str = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    # LLM fallback (optional — requires a running Ollama instance)
    # Photon geocoder for the train/bus station picker (segments/). Defaults to
    # komoot's public instance; point at a self-hosted one, or blank it out to
    # disable the lookup and leave the picker as plain free-text entry.
    PHOTON_URL: str = os.getenv("PHOTON_URL", "https://photon.komoot.io")

    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "180"))
    # Optional announcement banner shown to all users (empty = no banner)
    ANNOUNCEMENT: str = os.getenv("ANNOUNCEMENT", "")
    # CARTO basemap API key for the trip map's tiles. CARTO started watermarking
    # unkeyed raster tiles with "API KEY REQUIRED" in 2026; a free key is at
    # https://carto.com/basemaps/apikey. Left empty, the map falls back to plain
    # OpenStreetMap tiles, which need no key.
    CARTO_API_KEY: str = os.getenv("CARTO_API_KEY", "")


settings = Settings()
