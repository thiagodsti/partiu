"""
Version info endpoint. Returns the running version and checks GitHub for updates.
"""

import json
import os
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends

from ..auth import get_current_user

router = APIRouter(prefix="/api/version", tags=["version"])

GITHUB_REPO = "thiagodsti/partiu"
_cache: dict = {"ts": 0.0, "latest": None}
_CACHE_TTL = 6 * 3600  # 6 hours


def get_current_version() -> str:
    return os.environ.get("PARTIU_VERSION", "dev").strip()


def _fetch_latest_version() -> str | None:
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL and _cache["latest"] is not None:
        return _cache["latest"]
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "partiu-app"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "").lstrip("v")
            _cache["ts"] = now
            _cache["latest"] = tag or None
            return _cache["latest"]
    except Exception:
        return None


@router.get("")
def get_version(user: dict = Depends(get_current_user)):
    current = get_current_version()
    result: dict = {
        "current_version": current,
        "latest_version": None,
        "update_available": False,
    }
    if user.get("is_admin"):
        latest = _fetch_latest_version()
        if latest and current not in ("dev", "unknown"):
            result["latest_version"] = latest
            result["update_available"] = latest != current
    return result
