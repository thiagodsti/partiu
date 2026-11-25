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
    # Test servers only. The E2E suite signs in two dozen accounts and imports
    # dozens of mails from one address in a couple of minutes, which the per-IP
    # limits (5 sign-ins a minute) are there to stop. Never set it in production.
    DISABLE_RATE_LIMITS: bool = os.getenv("DISABLE_RATE_LIMITS", "false").lower() == "true"
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

    # KDE Itinerary's extractor, an extraction tier between the schema.org
    # reader and the LLM (parsers/kitinerary.py). The Docker image installs
    # KDE's static build here on x86_64; set it empty to switch the tier off.
    KITINERARY_EXTRACTOR: str = os.getenv(
        "KITINERARY_EXTRACTOR", "/opt/kitinerary/bin/kitinerary-extractor"
    )

    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "180"))
    # Context window per request. The system prompt alone is ~1000 tokens and
    # Ollama's default is 4096, which long itineraries overflow (Ollama then
    # answers 400). The longest mail of the 372-mail corpus needs ~4.3k tokens.
    OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    # Optional announcement banner shown to all users (empty = no banner)
    ANNOUNCEMENT: str = os.getenv("ANNOUNCEMENT", "")
    # CARTO basemap API key for the trip map's tiles. CARTO started watermarking
    # unkeyed raster tiles with "API KEY REQUIRED" in 2026; a free key is at
    # https://carto.com/basemaps/apikey. Left empty, the map falls back to plain
    # OpenStreetMap tiles, which need no key.
    CARTO_API_KEY: str = os.getenv("CARTO_API_KEY", "")
    # Public demo instance. With DEMO_MODE on, the login page publishes the
    # shared demo credentials so a visitor can sign straight in; off (the
    # default) the endpoint that serves them says nothing at all, because a
    # real install must never advertise a working password on its login page.
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() == "true"
    DEMO_USERNAME: str = os.getenv("DEMO_USERNAME", "demo")
    DEMO_PASSWORD: str = os.getenv("DEMO_PASSWORD", "demo1234")


settings = Settings()
