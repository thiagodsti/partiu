"""Configuration status of the optional third-party integrations.

Every integration here is optional: Partiu runs without any of them, each one
degrading a specific feature rather than breaking the app. That is why this is
a **status report and not a warning** — it is logged at INFO, never surfaced as
a banner, and an unconfigured integration is a legitimate choice rather than a
fault to nag about.

Two rules this module exists to keep:

* **A key's value never leaves the server.** Callers get "configured" or not,
  plus the name of the env var to set — never the secret itself.
* **`PHOTON_URL` is not a set-or-unset question.** It defaults to komoot's
  public instance, so a naive `bool(...)` check reports "configured" for
  something the admin never chose. It has three honest states, and the
  difference matters: the public instance is a shared, rate-limited service and
  every place a user types is sent to it.
"""

import logging
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)

# Photon's default in config.py. Compared against so the status can tell a
# deliberate self-hosted instance from the out-of-the-box public one.
PUBLIC_PHOTON_URL = "https://photon.komoot.io"


@dataclass
class IntegrationStatus:
    """One optional integration's configuration state.

    ``key`` is a stable identifier the frontend maps to a translated name and
    description — the human-readable strings live in the locale files, not here.
    ``state`` is machine-readable for the same reason.
    """

    key: str
    configured: bool
    # "set" | "unset" | "public_instance" | "self_hosted" | "disabled"
    state: str
    # The environment variable that configures it, or None when it is set up
    # through the UI instead.
    env_var: str | None


def _photon_status() -> IntegrationStatus:
    url = (settings.PHOTON_URL or "").strip()
    if not url:
        # Explicitly emptied: the pickers fall back to free-text entry.
        return IntegrationStatus("photon", False, "disabled", "PHOTON_URL")
    if url.rstrip("/") == PUBLIC_PHOTON_URL:
        return IntegrationStatus("photon", True, "public_instance", "PHOTON_URL")
    return IntegrationStatus("photon", True, "self_hosted", "PHOTON_URL")


def integration_statuses() -> list[IntegrationStatus]:
    """Every optional integration, in the order the Settings panel shows them."""
    return [
        IntegrationStatus(
            "carto",
            bool(settings.CARTO_API_KEY),
            "set" if settings.CARTO_API_KEY else "unset",
            "CARTO_API_KEY",
        ),
        IntegrationStatus(
            "aviationstack",
            bool(settings.AVIATIONSTACK_API_KEY),
            "set" if settings.AVIATIONSTACK_API_KEY else "unset",
            "AVIATIONSTACK_API_KEY",
        ),
        _photon_status(),
        IntegrationStatus(
            "ollama",
            bool(settings.OLLAMA_URL),
            "set" if settings.OLLAMA_URL else "unset",
            "OLLAMA_URL",
        ),
        # Generated from the Settings page rather than hand-set in .env, so no
        # env var is offered — telling an admin to edit VAPID_PRIVATE_KEY by
        # hand would be worse advice than the button that already exists.
        IntegrationStatus(
            "push",
            bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY),
            "set" if settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY else "unset",
            None,
        ),
    ]


def log_integration_summary() -> None:
    """One INFO line at startup.

    INFO rather than WARNING on purpose: these are optional, and warning about a
    deliberate configuration is how people learn to ignore warnings.
    """
    statuses = integration_statuses()
    configured = [s.key for s in statuses if s.configured and s.state != "public_instance"]
    missing = [s.key for s in statuses if not s.configured]
    public = [s.key for s in statuses if s.state == "public_instance"]

    parts = []
    if configured:
        parts.append(f"configured: {', '.join(configured)}")
    if missing:
        parts.append(f"not configured: {', '.join(missing)}")
    if public:
        parts.append(f"public instance: {', '.join(public)}")
    logger.info("Optional integrations — %s", "; ".join(parts) if parts else "none")
