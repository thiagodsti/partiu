"""Use cases for guests: a per-user address book of non-account trip participants."""

from ..auth import can_access_trip
from ..database import db_conn
from .domain import Guest
from .errors import (
    GuestInUseError,
    GuestNameTakenError,
    GuestNotFoundError,
    GuestOnTripError,
    GuestOnTripsError,
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

    def create(self, user_id: int, name: str) -> tuple[Guest, bool]:
        """Create a guest, or hand back the one this name already names.

        Returns `(guest, created)` — the guest rather than its id, because on a
        reuse the stored *spelling* is the existing row's ("jimmy" gets you
        "Jimmy") and the caller has to show the name the rest of the app uses. A person is not a row: typing "Jimmy" on a
        second trip when Jimmy is already in your address book means *that*
        Jimmy, and creating a second row made two identical names in every payer
        select with nothing to tell them apart — and split an expense history
        that belongs to one person across two ids. So an existing folded-name
        match wins, and `created` lets the caller say which happened rather than
        reporting a creation that did not occur.

        This is deliberately not a unique index on `(owner_id, name)`: the rule
        is folded equality, which SQLite cannot express, and a constraint would
        turn a reuse into an error the form has to recover from instead of the
        right answer.
        """
        clean = name.strip()
        if not clean:
            raise ValueError("Name cannot be empty")
        existing = self._repository.find_by_name(user_id, clean)
        if existing is not None:
            return existing, False
        guest_id = self._repository.create(user_id, clean)
        created = self._repository.get(guest_id)
        if created is None:  # pragma: no cover - the row was just written
            raise GuestNotFoundError(guest_id)
        return created, True

    def rename(self, guest_id: int, user_id: int, name: str) -> Guest:
        clean = name.strip()
        if not clean:
            raise ValueError("Name cannot be empty")
        guest = self._repository.get(guest_id)
        if guest is None or guest.owner_id != user_id:
            raise GuestNotFoundError(guest_id)
        # Refused rather than merged: create can reuse a row because nothing is
        # lost, but merging two guests here would have to move every expense
        # naming one of them onto the other, and the caller has not asked for
        # that. Renaming a guest to their own name in different case is fine —
        # `exclude_id` keeps the row from colliding with itself.
        clash = self._repository.find_by_name(user_id, clean, exclude_id=guest_id)
        if clash is not None:
            raise GuestNameTakenError(clash.name)
        self._repository.update(guest_id, user_id, clean)
        return Guest(id=guest.id, owner_id=guest.owner_id, name=clean, created_at=guest.created_at)

    def delete(self, guest_id: int, user_id: int, force: bool = False) -> None:
        """Delete a guest from the address book.

        Two things stand in the way, and they are not the same thing. An expense
        naming them is a **refusal**: the reference cannot be left dangling and
        no flag overrides it. Being on a trip's roster is a **warning**: the
        delete is allowed, but `trip_guests.guest_id` cascades, so it silently
        takes them off trips the caller is not looking at. That one names the
        trips and asks again — `force=True` is the caller saying yes.

        The refusal is reported **first**, even though the warning is cheaper to
        check: an expense naming a guest also puts them on that trip's roster,
        so testing the roster first would answer a confirmable warning to
        somebody whose delete is going to be refused whatever they answer.
        """
        guest = self._repository.get(guest_id)
        if guest is None or guest.owner_id != user_id:
            raise GuestNotFoundError(guest_id)
        referenced = self._repository.count_expense_references(guest_id)
        if referenced > 0:
            raise GuestInUseError(guest.name, referenced)
        if not force:
            trips = self._repository.trips_for_guest(guest_id)
            if trips:
                raise GuestOnTripsError(guest.name, trips)
        # Still routed through the atomic check: a concurrent request could have
        # tagged the guest in an expense since the count above.
        count = self._repository.delete_if_unused(guest_id, user_id)
        if count > 0:
            raise GuestInUseError(guest.name, count)


guest_service = GuestService()
