"""Use cases for guests: a per-user address book of non-account trip participants."""

from ..auth import can_access_trip
from ..database import db_conn
from .domain import Guest
from .errors import GuestInUseError, GuestNotFoundError, TripAccessError
from .guests_repository import GuestRepository


class GuestService:
    def __init__(self, repository: GuestRepository | None = None):
        self._repository = repository or GuestRepository()

    def list_mine(self, user_id: int) -> list[Guest]:
        return self._repository.list_for_owner(user_id)

    def list_for_trip(self, trip_id: str, user_id: int) -> list[Guest]:
        """Guests already tagged (as payer or participant) on this specific trip.

        Guests are scoped to the trip they're added to, not surfaced globally
        across every trip the caller has ever added a guest to — otherwise
        someone invited on a 2024 city break would keep showing up as a
        suggested participant on an unrelated 2026 trip. Any collaborator on
        the trip sees these, regardless of who created the guest."""
        with db_conn() as conn:
            if not can_access_trip(trip_id, user_id, conn):
                raise TripAccessError(trip_id)
        return self._repository.list_for_trip(trip_id)

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
        count = self._repository.count_references(guest_id)
        if count > 0:
            raise GuestInUseError(guest.name, count)
        self._repository.delete(guest_id, user_id)


guest_service = GuestService()
