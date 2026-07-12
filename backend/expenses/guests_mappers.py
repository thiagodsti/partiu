"""Conversions between domain objects and DTOs for the guests feature."""

from .domain import Guest
from .guests_dto import GuestDTO


def guest_to_dto(guest: Guest) -> GuestDTO:
    return GuestDTO(id=guest.id, name=guest.name, created_at=guest.created_at)
