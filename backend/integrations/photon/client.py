"""
Place lookup via Photon (https://photon.komoot.io) — komoot's open-source
geocoder over OpenStreetMap. Two callers: the train/bus station type-ahead in
``segments/`` and the accommodation/address type-ahead in ``stays/``.

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
import threading
import time

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
    # Accommodation. `tourism:apartment` covers the serviced-apartment listings
    # that Airbnb-style rentals are mapped as when they are mapped at all —
    # most private rentals are not in OSM, which is why the address fallback
    # below is not optional.
    "stay": (
        "tourism:hotel",
        "tourism:hostel",
        "tourism:guest_house",
        "tourism:apartment",
        "tourism:motel",
        "tourism:chalet",
    ),
}

# Station kinds only — `_ALL_TAGS` is the fallback for the station picker, and
# folding hotels into it would put them in the train-station dropdown.
_STATION_KINDS = ("train", "bus", "ferry")

# Falls back to searching every station kind when the caller has no preference.
_ALL_TAGS = tuple(tag for kind in _STATION_KINDS for tag in _OSM_TAGS[kind])

# OSM top-level keys that make a result a mapped *venue* rather than a street.
_PLACE_KEYS = frozenset({"railway", "amenity", "highway", "tourism", "leisure"})

# Below this many tagged hits, the stay picker also searches plain addresses.
_ADDRESS_FALLBACK_THRESHOLD = 3

# --- Response cache -------------------------------------------------------
#
# The picker fires a request per debounced keystroke, so typing "Hotel Aven"
# and then "Hotel Avenida" used to cost two full round trips to a public,
# rate-limited third-party service. Prefixes repeat constantly (backspacing,
# reopening the form, several people on one instance), so a small TTL cache
# removes most of the traffic without going stale in any way a user would
# notice — place names do not change minute to minute.
#
# Entries are kept for _CACHE_TTL_SECONDS and the map is bounded; a plain dict
# under a lock is enough at this size, and it means no new dependency.
_CACHE_TTL_SECONDS = 600.0
_CACHE_MAX_ENTRIES = 512

_cache: dict[tuple, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: tuple) -> list[dict] | None:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if now - stored_at > _CACHE_TTL_SECONDS:
            del _cache[key]
            return None
    # Copied on the way out so a caller mutating a result cannot corrupt the
    # cached entry for everyone else.
    return [dict(r) for r in value]


def _cache_put(key: tuple, value: list[dict]) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            # Cheapest useful eviction at this size: drop whatever is oldest.
            oldest = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest]
        _cache[key] = (time.monotonic(), [dict(r) for r in value])


def clear_cache() -> None:
    """Drop every cached lookup. Exists for tests, which must not see results
    another test warmed."""
    with _cache_lock:
        _cache.clear()


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


def _street_address(props: dict) -> str:
    """A one-line street address from Photon's components, or "".

    Assembled here rather than in the caller because the stay picker needs it
    for the calendar export's LOCATION field, which is what makes the entry
    tappable through to a maps app. Photon fills these inconsistently, so every
    part is optional and the result may legitimately be empty.
    """
    house = (props.get("housenumber") or "").strip()
    street = (props.get("street") or "").strip()
    line = f"{street} {house}".strip() if street else ""
    parts = [line, (props.get("postcode") or "").strip(), _city(props)]
    return ", ".join(p for p in parts if p)


def _fetch(params: list[tuple[str, str | int | float | None]], path: str, what: str) -> list[dict]:
    """One Photon call. Returns [] on any failure — callers treat an empty list
    and an unreachable geocoder identically, which is what lets the pickers fall
    back to free-text entry."""
    try:
        response = httpx.get(
            f"{settings.PHOTON_URL.rstrip('/')}{path}",
            params=params,
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("features", [])
    except Exception as e:
        logger.warning("Photon %s failed: %s", what, e)
        return []


def _to_result(feature: dict) -> dict | None:
    props = feature.get("properties") or {}
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coords) < 2:
        return None
    name = _label(props)
    if not name:
        return None
    return {
        "name": name,
        "city": _city(props),
        "address": _street_address(props),
        "country": (props.get("country") or "").strip(),
        "countrycode": (props.get("countrycode") or "").strip(),
        # 'place' is a mapped venue (a station, a hotel); 'address' is a street
        # or building. The stay picker groups on this, because a private rental
        # is only ever findable as the latter.
        "category": "place" if props.get("osm_key") in _PLACE_KEYS else "address",
        "lon": float(coords[0]),
        "lat": float(coords[1]),
        "osm_id": props.get("osm_id"),
    }


def _collect(features: list[dict], limit: int, into: list[dict], seen: set) -> None:
    for feature in features:
        result = _to_result(feature)
        if result is None:
            continue
        # Large venues are frequently mapped as several nodes a few metres apart
        # (Xi'an North comes back twice); collapsing on name+city keeps the
        # picker readable.
        key = (result["name"].casefold(), result["city"].casefold())
        if key in seen:
            continue
        seen.add(key)
        into.append(result)
        if len(into) >= limit:
            return


def search_places(query: str, kind: str | None = None, limit: int = 8) -> list[dict]:
    """Type-ahead candidates for a place.

    ``kind`` selects the OSM tag filter: a station kind ("train"/"bus"/"ferry"),
    "stay" for accommodation, or None to search every station kind.

    For "stay" this may issue a **second, untagged** call. Hotels are mapped in
    OSM and searchable by name, but a private rental usually is not — its
    address is all the guest has, and often all the booking gave them. Tagged
    results come first because they are the higher-confidence match; the untagged
    pass only runs when the tagged one came back thin, so typing a hotel name
    still costs a single request.
    """
    query = query.strip()
    if not query or not is_configured():
        return []

    limit = max(1, min(limit, _MAX_LIMIT))
    cache_key = ("search", query.casefold(), kind or "", limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    tags = _OSM_TAGS.get(kind or "", _ALL_TAGS)

    def params_for(with_tags: bool) -> list[tuple[str, str | int | float | None]]:
        # Typed to httpx's own query-param element type: repeated `osm_tag` keys
        # mean this has to be a list of pairs, not a dict.
        params: list[tuple[str, str | int | float | None]] = [
            ("q", query),
            ("lang", "en"),
            # Over-fetch: deduplication can collapse several features into one.
            ("limit", str(limit * 3)),
        ]
        if with_tags:
            params.extend(("osm_tag", tag) for tag in tags)
        return params

    results: list[dict] = []
    seen: set[tuple[str, str]] = set()
    _collect(_fetch(params_for(True), "/api/", f"lookup for {query!r}"), limit, results, seen)

    if kind == "stay" and len(results) < _ADDRESS_FALLBACK_THRESHOLD:
        _collect(
            _fetch(params_for(False), "/api/", f"address lookup for {query!r}"),
            limit,
            results,
            seen,
        )

    _cache_put(cache_key, results)
    return results


def search_stations(query: str, kind: str | None = None, limit: int = 8) -> list[dict]:
    """Station type-ahead — ``search_places`` restricted to station kinds.

    Kept as its own name because `/api/stations/search` is an existing endpoint
    and a "stay" reaching it would put hotels in the train-station dropdown.
    """
    return search_places(query, kind if kind in _STATION_KINDS else None, limit)


def reverse_country(lat: float, lon: float) -> str | None:
    """The ISO-3166-1 alpha-2 country at these coordinates, or None.

    Used to backfill the country of places stored before it was recorded. It is
    a real lookup rather than an inference: picking the nearest airport out of
    the local `airports` table was measured first and put Malmö Central in
    Denmark, because Copenhagen's airport is closer to it than any Swedish one.
    A wrong country presented as a visited fact is worse than no country, so
    this returns None rather than guessing when Photon is unavailable.
    """
    if not is_configured():
        return None

    # Rounded to ~1km before caching: the backfill walks many places, and two
    # stations in the same city are certainly in the same country.
    cache_key = ("reverse", round(lat, 2), round(lon, 2))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached[0]["code"] if cached else None

    features = _fetch(
        [("lat", lat), ("lon", lon), ("lang", "en")],
        "/reverse",
        f"reverse lookup for ({lat}, {lon})",
    )
    for feature in features:
        code = ((feature.get("properties") or {}).get("countrycode") or "").strip()
        if code:
            _cache_put(cache_key, [{"code": code.upper()}])
            return code.upper()
    # A miss is cached too, so a coordinate the geocoder cannot place does not
    # get retried on every pass.
    _cache_put(cache_key, [])
    return None
