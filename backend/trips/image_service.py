"""Fetches and caches a trip's destination photo from Wikipedia — a distinct
concern from trip CRUD, kept out of service.py."""

import random
from pathlib import Path

from ..integrations.wikipedia.client import fetch_trip_image, find_trip_image
from .errors import TripError
from .repository import TripRepository


class TripImageService:
    def __init__(self, repository: TripRepository | None = None):
        self._repository = repository or TripRepository()

    def _resolve_destination_city(self, trip_id: str) -> str | None:
        """The city whose photo becomes this trip's cover.

        A **typed** destination wins: those are the only places a person chose,
        they are already populated places (the picker filters to city/town/
        village), and they are all a trip with no flights has. One is picked at
        random, so "find a different image" on a multi-stop trip can move
        between its cities rather than re-rolling photos of the first one.

        Only when there are none does this fall back to the destination
        airport's city, then to the last flight's arrival airport — which is why
        a rail or road trip had no cover photo at all before: an IATA code was
        the only handle.
        """
        destinations = self._repository.list_destinations([trip_id]).get(trip_id, [])
        names = [
            cleaned
            for place in destinations
            if (cleaned := place["name"].split("(")[0].split(",")[0].strip())
        ]
        if names:
            return random.choice(names)

        iata = self._repository.get_destination_airport(trip_id)
        if not iata:
            iata = self._repository.get_last_flight_arrival_airport(trip_id)
        if not iata:
            return None

        city = self._repository.get_airport_city(iata) or iata
        # Strip parenthetical suffix (e.g. "Paris (Roissy-en-France)" → "Paris")
        # then strip region/state suffix (e.g. "London, Essex" → "London")
        if city:
            city = city.split("(")[0].split(",")[0].strip()
        return city or iata

    async def get_trip_image_path(self, trip_id: str, user_id: int) -> Path:
        """Return the on-disk Path to the trip's cached destination photo,
        fetching it on first request. Raises TripError if none is available."""
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)
        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripError("Trip not found", 404)

        existing = find_trip_image(trip_id)
        if existing:
            return existing

        # Already attempted and failed — don't hammer Wikipedia on every request
        if trip.image_fetched_at:
            raise TripError("No image available", 404)

        city_name = self._resolve_destination_city(trip_id)
        if not city_name:
            raise TripError("No destination city found", 404)

        success = await fetch_trip_image(trip_id, city_name)
        self._repository.set_image_fetched_at(trip_id, _now_iso())

        existing = find_trip_image(trip_id)
        if success and existing:
            return existing

        raise TripError("No image available", 404)

    async def refresh_trip_image(self, trip_id: str, user_id: int) -> None:
        """Delete the current image and fetch a different random one."""
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)

        city_name = self._resolve_destination_city(trip_id)
        if not city_name:
            raise TripError("No destination city found", 404)

        success = await fetch_trip_image(trip_id, city_name, force_refresh=True)
        self._repository.set_image_fetched_at(trip_id, _now_iso())

        if success and find_trip_image(trip_id):
            return

        raise TripError("No image available", 404)

    def _can_access(self, trip_id: str, user_id: int) -> bool:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)


def _now_iso() -> str:
    from ..utils import now_iso

    return now_iso()


trip_image_service = TripImageService()
