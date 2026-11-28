"""The Wikipedia article about a suggested place: its photo and its position.

Text models cannot see photos and invent image URLs that look right and open
the wrong picture or none, so a photo never comes from the model. Each
suggestion is searched on Wikipedia by name and city; an article counts only
when its title is about that place (``names.article_is_about``) **and** its
coordinates lie near the city. Such an article is also the cheapest check that
the place exists, and its coordinates are what put the pin on the map — so most
sights and museums need no geocoder at all. Restaurants and bars rarely have an
article; theirs is looked up on the map only when the traveller adds one.

Every failure here — Wikipedia down, slow, nothing found — is simply "no
article".
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from .names import article_is_about, km

logger = logging.getLogger(__name__)

_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia asks every client for a descriptive User-Agent.
_HEADERS = {
    "User-Agent": "Partiu/1.0 (self-hosted trip planner; https://github.com/thiagodsti/partiu)"
}
_TIMEOUT = 5.0
THUMB_PX = 320


def article_for(name: str, city: str, centre: tuple[float, float], max_km: float) -> dict | None:
    """``{"image_url", "page_url", "lat", "lon"}`` for the article about this
    place, or None. ``image_url`` may be None: an article without a photo
    still places the pin."""
    try:
        r = httpx.get(
            _API,
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{name} {city}",
                "gsrlimit": 4,
                "prop": "pageimages|coordinates|info",
                "piprop": "thumbnail",
                "pithumbsize": THUMB_PX,
                "inprop": "url",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
    except Exception as e:  # any failure is "no article"
        logger.info("Wikipedia lookup failed for %r: %s", name, e)
        return None

    # Search order is relevance; keep it.
    for page in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        title = page.get("title") or ""
        coords = (page.get("coordinates") or [{}])[0]
        if "lat" not in coords or "lon" not in coords:
            continue
        if not article_is_about(name, title):
            continue
        if km(centre, (coords["lat"], coords["lon"])) > max_km:
            continue
        return {
            "image_url": (page.get("thumbnail") or {}).get("source"),
            "page_url": page.get("fullurl") or "",
            "lat": coords["lat"],
            "lon": coords["lon"],
        }
    return None


def add_articles(cards: list[dict], city: str, centre: tuple[float, float], max_km: float) -> None:
    """Fill ``image_url`` / ``image_page`` / ``lat`` / ``lon`` / ``on_wikipedia``
    on each card in place."""

    def one(card: dict) -> dict | None:
        return article_for(card["title"], city, centre, max_km)

    # Wikipedia welcomes a few parallel requests; the cards are a handful.
    with ThreadPoolExecutor(max_workers=3) as pool:
        found = list(pool.map(one, cards))
    for card, article in zip(cards, found, strict=True):
        card["on_wikipedia"] = article is not None
        card["image_url"] = article["image_url"] if article else None
        card["image_page"] = article["page_url"] if article else None
        card["lat"] = article["lat"] if article else None
        card["lon"] = article["lon"] if article else None
