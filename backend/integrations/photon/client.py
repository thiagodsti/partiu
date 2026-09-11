"""
Station lookup via Photon (https://photon.komoot.io) — komoot's open-source
geocoder over OpenStreetMap, used for the train/bus station type-ahead in
``segments/``.

Why Photon and not a local dataset: GeoNames' station coverage is the obvious
offline alternative, but measured against China it holds 669 stations where OSM
holds 17,320, and Xi'an North — one of the country's largest HSR hubs — is
absent from it entirely. Coverage, not convenience, is why this is a network
call.

Two things are load-bearing in the request:

* ``lang=en`` — without it Photon answers in the local script (``北京西``) and
  Latin-script queries barely match at all.
* ``osm_tag`` — ``railway:station`` / ``amenity:bus_station`` keeps the results
  to actual stations instead of every street and shop that shares the name.

``railway:station`` also covers metro stops, and OSM's ``station=subway``
distinguisher is not exposed in Photon's response, so a query for "Beijing West"
legitimately returns subway stations too. The picker shows city and country per
result and lets the user choose — filtering that here would need data the API
does not return.

The caller decides what to do when this returns nothing: the segment form falls
back to free-text entry, so an unreachable geocoder costs the map line and the
timezone conversion, not the ability to record the journey.
"""

import logging

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 6.0
_MAX_LIMIT = 15

# Photon returns one feature per OSM node, and large stations are frequently
# mapped as several nodes a few metres apart (Xi'an North comes back twice).
# Collapsing on name+city keeps the picker readable.
_OSM_TAGS: dict[str, tuple[str, ...]] = {
    "train": ("railway:station",),
    "bus": ("amenity:bus_station", "highway:bus_stop"),
    "ferry": ("amenity:ferry_terminal",),
}

# Falls back to searching every station kind when the caller has no preference.
_ALL_TAGS = tuple(tag for tags in _OSM_TAGS.values() for tag in tags)

_HEADERS = {
    "User-Agent": "Partiu/1.0 (self-hosted flight tracker; https://github.com/thiagodsti/partiu)"
}


def is_configured() -> bool:
    return bool(settings.PHOTON_URL)


def _label(props: dict) -> str:
    """Human-readable place name. Photon's ``name`` is the station itself; the
    city is appended separately by the caller for display."""
    return (props.get("name") or props.get("street") or "").strip()


def _city(props: dict) -> str:
    # Photon fills these inconsistently by country — `city` is missing for many
    # Chinese stations where `county`/`district` carries the useful name.
    for key in ("city", "district", "county", "state"):
        value = props.get(key)
        if value:
            return str(value).strip()
    return ""


def search_stations(query: str, kind: str | None = None, limit: int = 8) -> list[dict]:
    """Return station candidates for a type-ahead query.

    Each result is ``{name, city, country, countrycode, lat, lon, osm_id}``.
    Returns ``[]`` on any failure — the caller treats an empty list and an
    unreachable geocoder identically.
    """
    query = query.strip()
    if not query or not is_configured():
        return []

    limit = max(1, min(limit, _MAX_LIMIT))
    tags = _OSM_TAGS.get(kind or "", _ALL_TAGS)

    # Typed to httpx's own query-param element type: repeated `osm_tag` keys
    # mean this has to be a list of pairs, not a dict.
    params: list[tuple[str, str | int | float | None]] = [
        ("q", query),
        ("lang", "en"),
        # Over-fetch: deduplication below can collapse several features into one.
        ("limit", str(limit * 3)),
    ]
    params.extend(("osm_tag", tag) for tag in tags)

    try:
        response = httpx.get(
            f"{settings.PHOTON_URL.rstrip('/')}/api/",
            params=params,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        features = response.json().get("features", [])
    except Exception as e:
        logger.warning("Photon station lookup failed for %r: %s", query, e)
        return []

    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for feature in features:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        name = _label(props)
        if not name:
            continue
        city = _city(props)
        dedupe_key = (name.casefold(), city.casefold())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(
            {
                "name": name,
                "city": city,
                "country": (props.get("country") or "").strip(),
                "countrycode": (props.get("countrycode") or "").strip(),
                "lon": float(coords[0]),
                "lat": float(coords[1]),
                "osm_id": props.get("osm_id"),
            }
        )
        if len(results) >= limit:
            break

    return results
