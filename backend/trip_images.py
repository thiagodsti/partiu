"""
Fetch and cache destination images for trips from Wikipedia.

Images are stored as data/images/trips/{trip_id}.webp (800px wide, WebP).
Legacy .jpg files are still served if present; new fetches always produce .webp.
Uses a single Wikipedia API call (generator=images) to get image URLs,
falling back to the pageimages thumbnail if that returns nothing.
"""

import io
import logging
import random
from pathlib import Path

import httpx
from PIL import Image

from .config import settings

logger = logging.getLogger(__name__)

_MAX_WIDTH = 800
_WEBP_QUALITY = 82

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
    """Canonical path for a trip image (WebP). New images are always saved here."""
    return _images_dir() / f"{trip_id}.webp"


def find_trip_image(trip_id: str) -> Path | None:
    """Return the path to an existing trip image, preferring .webp over legacy .jpg."""
    webp = trip_image_path(trip_id)
    if webp.exists():
        return webp
    jpg = _images_dir() / f"{trip_id}.jpg"
    if jpg.exists():
        return jpg
    return None


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


def _resize_and_encode_webp(raw: bytes) -> bytes:
    """Resize to at most _MAX_WIDTH wide and encode as WebP."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if img.width > _MAX_WIDTH:
        ratio = _MAX_WIDTH / img.width
        img = img.resize((_MAX_WIDTH, int(img.height * ratio)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=_WEBP_QUALITY, method=4)
    return out.getvalue()


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
    Fetch a destination photo for a trip and save it to disk as WebP.

    On force_refresh the existing file is deleted so a different random photo is picked.
    Returns True if an image was saved successfully.
    """
    dest = trip_image_path(trip_id)  # .webp canonical path

    if force_refresh:
        dest.unlink(missing_ok=True)
        # Also remove legacy jpg so find_trip_image won't return the old one
        (dest.with_suffix(".jpg")).unlink(missing_ok=True)

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
                    try:
                        webp_bytes = _resize_and_encode_webp(r.content)
                    except Exception as e:
                        logger.warning("Image processing failed for %s: %s", url, e)
                        continue
                    dest.write_bytes(webp_bytes)
                    logger.info("Saved trip image (WebP): %s", dest)
                    return True
            except Exception as e:
                logger.warning("Download failed for %s: %s", url, e)

    return False
