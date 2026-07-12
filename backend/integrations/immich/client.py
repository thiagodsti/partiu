"""
Immich integration — create photo albums from trip date ranges.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


async def test_connection(base_url: str, api_key: str) -> dict:
    """
    Test the Immich connection and API key.
    - First checks server reachability via the public ping endpoint.
    - Then validates the API key via a minimal asset search (requires asset.read).
    Returns {'ok': True, 'version': '...'} or raises ValueError.
    """
    base = base_url.rstrip("/")
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Step 1: reachability + version (public endpoint, no auth needed)
            ping = await client.get(f"{base}/api/server/ping")
            if ping.status_code not in (200, 401, 403):
                raise ValueError(f"Server not reachable at {base} (HTTP {ping.status_code})")

            version = "unknown"
            about = await client.get(f"{base}/api/server/about", headers={"x-api-key": api_key})
            if about.status_code == 200:
                body = about.json()
                version = body.get("version") or body.get("releaseVersion") or "unknown"

            # Step 2: validate API key by performing a minimal asset search
            search = await client.post(
                f"{base}/api/search/metadata",
                headers=headers,
                json={"page": 1, "size": 1},
            )
            if search.status_code == 401:
                raise ValueError("Invalid API key")
            if search.status_code == 403:
                raise ValueError("API key lacks required permissions (need asset.read)")
            if search.status_code != 200:
                raise ValueError(f"API key validation failed: HTTP {search.status_code}")

        return {"ok": True, "version": version}
    except ValueError:
        raise
    except httpx.TimeoutException:
        raise ValueError("Connection timed out")
    except Exception as e:
        raise ValueError(f"Connection error: {e}") from e


async def _get_asset_ids_in_range(
    base_url: str, api_key: str, start_date: str, end_date: str
) -> list[str]:
    """Return all asset IDs with takenDate between start_date and end_date (inclusive)."""
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    taken_after = f"{start_date}T00:00:00.000Z"
    taken_before = f"{end_date}T23:59:59.999Z"

    asset_ids: list[str] = []
    page = 1

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        while True:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/search/metadata",
                headers=headers,
                json={
                    "takenAfter": taken_after,
                    "takenBefore": taken_before,
                    "page": page,
                    "size": 1000,
                },
            )
            if resp.status_code != 200:
                logger.warning("Immich search/metadata failed: HTTP %d", resp.status_code)
                break
            data = resp.json()
            items = data.get("assets", {}).get("items", [])
            for item in items:
                asset_ids.append(item["id"])
            if not items or not data.get("assets", {}).get("nextPage"):
                break
            page += 1

    return asset_ids


async def album_exists(base_url: str, api_key: str, album_id: str) -> bool:
    """Return True if the album still exists in Immich.
    Only an explicit 404 means the album is gone — any other response (auth error,
    network issue, server error) is treated as "assume it exists" to avoid
    accidentally clearing a valid album_id.
    """
    headers = {"x-api-key": api_key}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/api/albums/{album_id}",
                headers=headers,
            )
        return resp.status_code != 404
    except Exception:
        return True  # network/timeout — assume it still exists


async def create_trip_album(
    base_url: str, api_key: str, album_name: str, start_date: str, end_date: str
) -> dict:
    """
    Find photos in the trip date range and create an Immich album.
    Returns {'album_id': str, 'album_url': str, 'asset_count': int}.
    Raises ValueError on any Immich API error.
    """
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    base = base_url.rstrip("/")

    try:
        asset_ids = await _get_asset_ids_in_range(base, api_key, start_date, end_date)

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/api/albums",
                headers=headers,
                json={"albumName": album_name, "assetIds": asset_ids},
            )

        if resp.status_code not in (200, 201):
            raise ValueError(f"Failed to create album: HTTP {resp.status_code} — {resp.text[:200]}")

        data = resp.json()
        album_id = data["id"]

    except ValueError:
        raise
    except httpx.TimeoutException:
        raise ValueError("Immich request timed out")
    except Exception as e:
        raise ValueError(f"Immich error: {e}") from e

    return {
        "album_id": album_id,
        "album_url": f"{base}/albums/{album_id}",
        "asset_count": len(asset_ids),
    }
