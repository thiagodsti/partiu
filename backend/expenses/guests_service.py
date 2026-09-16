"""Use cases for guests: a per-user address book of non-account trip participants."""

from ..auth import can_access_trip
from ..database import db_conn
from .domain import Guest
from .errors import (
    GuestInUseError,
    GuestNotFoundError,
    GuestOnTripError,
    TripAccessError,
)
from .guests_repository import GuestRepository


class GuestService:
    def __init__(self, repository: GuestRepository | None = None):
        self._repository = repository or GuestRepository()

    def list_mine(self, user_id: int) -> list[Guest]:
        return self._repository.list_for_owner(user_id)

    def list_for_trip(self, trip_id: str, user_id: int) -> list[Guest]:
        """The guests on this trip, from its roster.

        Guests are scoped to the trip they are put on, not surfaced globally
        across every trip the caller has ever added one to — otherwise someone
        invited on a 2024 city break would keep showing up as a suggested
        participant on an unrelated 2026 trip. Any collaborator on the trip sees
        these, regardless of who created the guest."""
        with db_conn() as conn:
            if not can_access_trip(trip_id, user_id, conn):
                raise TripAccessError(trip_id)
        return self._repository.list_for_trip(trip_id)

    def add_to_trip(self, trip_id: str, guest_id: int, user_id: int) -> Guest:
        """Put one of the caller's own guests on a trip they can access.

        Ownership of the guest is still the caller's — the roster says who is
        travelling, not who the address-book entry belongs to. Idempotent, so a
        double-submit is not an error.
        """
        with db_conn() as conn:
            if not can_access_trip(trip_id, user_id, conn):
                raise TripAccessError(trip_id)
        guest = self._repository.get(guest_id)
        if guest is None or guest.owner_id != user_id:
            raise GuestNotFoundError(guest_id)
        self._repository.add_to_trip(trip_id, guest_id)
        return guest

    def remove_from_trip(self, trip_id: str, guest_id: int, user_id: int) -> None:
        """Take a guest off a trip, refusing while an expense there names them.

        The guest itself is untouched — they stay in the address book and on any
        other trip. Only this trip's roster changes.
        """
        with db_conn() as conn:
            if not can_access_trip(trip_id, user_id, conn):
                raise TripAccessError(trip_id)
        guest = self._repository.get(guest_id)
        if guest is None:
            raise GuestNotFoundError(guest_id)
        if self._repository.is_used_on_trip(trip_id, guest_id):
            raise GuestOnTripError(guest.name)
        self._repository.remove_from_trip(trip_id, guest_id)

    def create(self, user_id: int, name: str) -> int:
        clean = name.strip()
        if not clean:
            raise ValueError("Name cannot be empty")
        return self._repository.create(user_id, clean)

    def rename(self, guest_id: int, user_id: int, name: str) -> Guest:
        clean = name.strip()
        if not clean:
            raise ValueError("Name cannot be empty")
        guest = self._repository.get(guest_id)
        if guest is None or guest.owner_id != user_id:
            raise GuestNotFoundError(guest_id)
        self._repository.update(guest_id, user_id, clean)
        return Guest(id=guest.id, owner_id=guest.owner_id, name=clean, created_at=guest.created_at)

    def delete(self, guest_id: int, user_id: int) -> None:
        guest = self._repository.get(guest_id)
        if guest is None or guest.owner_id != user_id:
            raise GuestNotFoundError(guest_id)
        count = self._repository.delete_if_unused(guest_id, user_id)
        if count > 0:
            raise GuestInUseError(guest.name, count)


guest_service = GuestService()
