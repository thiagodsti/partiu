import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings

limiter = Limiter(key_func=get_remote_address, enabled=not settings.DISABLE_RATE_LIMITS)

if settings.DISABLE_RATE_LIMITS:
    # A warning, unlike the optional-integration summary: this is not a missing
    # feature but a removed defence, and it should never be on outside a test run.
    logging.getLogger(__name__).warning(
        "DISABLE_RATE_LIMITS is on: sign-in and other per-IP limits are not enforced"
    )
