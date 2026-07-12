"""Immich album creation/status-check orchestration for a trip: resolves the
user's Immich credentials and persists the linked album id, delegating the
actual HTTP calls to integrations.immich.client."""

import logging

from ..crypto import decrypt
from .domain import ImmichAlbumResult, ImmichAlbumStatus
from .errors import TripError
from .repository import TripRepository

logger = logging.getLogger(__name__)


class TripImmichService:
    def __init__(self, repository: TripRepository | None = None):
        self._repository = repository or TripRepository()

    async def check_immich_album(self, trip_id: str, user_id: int) -> ImmichAlbumStatus:
        """Check whether the stored Immich album still exists (does NOT clear the
        DB entry if deleted — the create endpoint handles that cleanup)."""
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)

        album_id = self._repository.get_immich_album_id(trip_id, user_id)
        if not album_id:
            return ImmichAlbumStatus(album_id=None, exists=False)

        immich_url, immich_api_key = self._get_immich_credentials(user_id)
        if not immich_url or not immich_api_key:
            return ImmichAlbumStatus(
                album_id=album_id, exists=True
            )  # can't check — assume it exists

        from ..integrations.immich.client import album_exists

        exists = await album_exists(immich_url, immich_api_key, album_id)
        return ImmichAlbumStatus(album_id=album_id if exists else None, exists=exists)

    async def create_immich_album(self, trip_id: str, user_id: int) -> ImmichAlbumResult:
        """Create an Immich album with photos from this trip's date range, or
        return the existing one."""
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripError("Trip not found", 404)

        immich_url, immich_api_key = self._get_immich_credentials(user_id)
        stored_album_id = self._repository.get_immich_album_id(trip_id, user_id)

        if not trip.start_date or not trip.end_date:
            raise TripError("Trip must have start and end dates to create an album", 400)

        # If an album ID is stored, verify it still exists in Immich before returning the cached link
        if stored_album_id and immich_url and immich_api_key:
            from ..integrations.immich.client import album_exists

            if await album_exists(immich_url, immich_api_key, stored_album_id):
                base = immich_url.rstrip("/")
                album_url = f"{base}/albums/{stored_album_id}"
                return ImmichAlbumResult(
                    album_id=stored_album_id,
                    album_url=album_url,
                    asset_count=None,
                    already_exists=True,
                )
            # Album was deleted in Immich — clear the stored ID and recreate below
            self._repository.delete_immich_album(trip_id, user_id)

        if not immich_url or not immich_api_key:
            raise TripError(
                "Immich is not configured. Add your Immich URL and API key in Settings.", 400
            )

        from ..integrations.immich.client import create_trip_album

        try:
            result = await create_trip_album(
                base_url=immich_url,
                api_key=immich_api_key,
                album_name=trip.name,
                start_date=trip.start_date,
                end_date=trip.end_date,
            )
        except ValueError as e:
            raise TripError(str(e), 502) from e
        except Exception as e:
            logger.error("Immich album creation failed for trip %s: %s", trip_id, e)
            raise TripError(f"Immich error: {e}", 502) from e

        self._repository.save_immich_album(trip_id, user_id, result["album_id"])
        return ImmichAlbumResult(
            album_id=result["album_id"],
            album_url=result["album_url"],
            asset_count=result["asset_count"],
            already_exists=False,
        )

    def _get_immich_credentials(self, user_id: int) -> tuple[str, str]:
        row = self._repository.get_immich_credentials(user_id)
        immich_url = (row["immich_url"] or "").strip() if row else ""
        immich_api_key = decrypt((row["immich_api_key"] or "").strip()) if row else ""
        return immich_url, immich_api_key

    def _can_access(self, trip_id: str, user_id: int) -> bool:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)


trip_immich_service = TripImmichService()
