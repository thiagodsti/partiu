"""
Fetch and cache destination images for trips from Wikipedia.

Images are stored as data/images/trips/{trip_id}.jpg.
Uses a single Wikipedia API call (generator=images) to get image URLs,
falling back to the pageimages thumbnail if that returns nothing.
"""

import logging
import random
from pathlib import Path

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# Wikimedia requires a descriptive User-Agent with contact info
_HEADERS = {
    "User-Agent": "Partiu/1.0 (self-hosted flight tracker; https://github.com/thiagodsti/partiu)"
}

# Substrings in image titles that indicate non-photo files
_SKIP_KEYWORDS = frozenset(
    [
        "flag",
        "coat_of_arms",
        "logo",
        "icon",
        "map",
        "svg",
        "blank",
        "symbol",
        "seal",
        "emblem",
        "locator",
        "outline",
        "relief",
    ]
)


def _images_dir() -> Path:
    d = Path(settings.DB_PATH).parent / "images" / "trips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def trip_image_path(trip_id: str) -> Path:
    return _images_dir() / f"{trip_id}.jpg"


def _parse_json_safe(r: httpx.Response) -> dict:
    """Return parsed JSON only for 2xx responses; log and return {} otherwise."""
    if r.status_code != 200:
        logger.warning("Wikipedia API returned %d: %s", r.status_code, r.text[:200])
        return {}
    try:
        return r.json()
    except Exception as e:
        logger.warning("Wikipedia API non-JSON response (%d): %s", r.status_code, e)
        return {}


async def _get_photo_urls(city_name: str) -> list[str]:
    """
    Return a shuffled list of landscape JPEG URLs from the city's Wikipedia article.
    Uses a single API call (generator=images + imageinfo) instead of two.
    Falls back to the main article thumbnail if the generator returns nothing.
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # Single call: generator=images gives us all image files cited in the article
        # with their download URLs included via prop=imageinfo
        r = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "images",
                "titles": city_name,
                "prop": "imageinfo",
                "iiprop": "url|dimensions|mime",
                "iiurlwidth": 1000,
                "format": "json",
                "formatversion": "2",
                "gimlimit": 50,
                "redirects": 1,
            },
            headers=_HEADERS,
        )
        data = _parse_json_safe(r)
        urls: list[str] = []
        for page in data.get("query", {}).get("pages", []):
            title: str = page.get("title", "")
            lower = title.lower()
            if any(k in lower for k in _SKIP_KEYWORDS):
                continue
            if not lower.endswith((".jpg", ".jpeg")):
                continue
            for info in page.get("imageinfo", []):
                mime = info.get("mime", "")
                url = info.get("thumburl") or info.get("url", "")
                w = info.get("thumbwidth") or info.get("width") or 0
                h = info.get("thumbheight") or info.get("height") or 0
                if url and mime in ("image/jpeg", "image/jpg") and w and h and w >= h * 0.8:
                    urls.append(url)

        if urls:
            random.shuffle(urls)
            return urls

        # Fallback: use the article's main thumbnail (pageimages)
        r2 = await client.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": city_name,
                "prop": "pageimages",
                "format": "json",
                "formatversion": "2",
                "pithumbsize": 1000,
                "piprop": "thumbnail",
                "redirects": 1,
            },
            headers=_HEADERS,
        )
        data2 = _parse_json_safe(r2)
        for page in data2.get("query", {}).get("pages", []):
            thumb = page.get("thumbnail", {})
            if thumb.get("source"):
                return [thumb["source"]]

    return []


async def fetch_trip_image(trip_id: str, city_name: str, force_refresh: bool = False) -> bool:
    """
    Fetch a destination photo for a trip and save it to disk.

    On force_refresh the existing file is deleted so a different random photo is picked.
    Returns True if an image was saved successfully.
    """
    dest = trip_image_path(trip_id)

    if force_refresh and dest.exists():
        dest.unlink()

    if dest.exists():
        return True

    logger.info(
        "Fetching trip image for %s, city=%s (refresh=%s)", trip_id, city_name, force_refresh
    )

    urls = await _get_photo_urls(city_name)
    if not urls:
        logger.info("No images found for city=%s", city_name)
        return False

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url, headers=_HEADERS)
                if r.status_code == 200 and r.content:
                    dest.write_bytes(r.content)
                    logger.info("Saved trip image: %s", dest)
                    return True
            except Exception as e:
                logger.warning("Download failed for %s: %s", url, e)

    return False
