"""Conversions between SQL rows, domain objects and DTOs."""

import json
import sqlite3

from .domain import Trip
from .dto import TripDetailDTO, TripListItemDTO


def row_to_trip(row: sqlite3.Row) -> Trip:
    try:
        booking_refs = json.loads(row["booking_refs"] or "[]")
    except (json.JSONDecodeError, TypeError):
        booking_refs = []
    return Trip(
        id=row["id"],
        name=row["name"],
        booking_refs=booking_refs,
        start_date=row["start_date"],
        end_date=row["end_date"],
        origin_airport=row["origin_airport"],
        destination_airport=row["destination_airport"],
        is_auto_generated=row["is_auto_generated"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        image_fetched_at=row["image_fetched_at"],
        rating=row["rating"],
        note=row["note"],
    )


def trip_to_list_item_dto(
    trip: Trip,
    *,
    is_owner: bool,
    owner_username: str | None,
    flight_count: int,
    expenses_total: dict[str, float],
    immich_album_id: str | None,
    search_index: str,
) -> TripListItemDTO:
    return TripListItemDTO(
        id=trip.id,
        name=trip.name,
        booking_refs=trip.booking_refs,
        start_date=trip.start_date,
        end_date=trip.end_date,
        origin_airport=trip.origin_airport,
        destination_airport=trip.destination_airport,
        is_auto_generated=trip.is_auto_generated,
        user_id=trip.user_id,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
        image_fetched_at=trip.image_fetched_at,
        rating=trip.rating,
        note=trip.note,
        is_owner=is_owner,
        owner_username=owner_username,
        flight_count=flight_count,
        expenses_total=expenses_total,
        immich_album_id=immich_album_id,
        search_index=search_index,
    )


def trip_to_detail_dto(
    trip: Trip,
    *,
    is_owner: bool,
    owner_username: str | None,
    flights: list[dict],
    expenses_total: dict[str, float],
    immich_album_id: str | None,
) -> TripDetailDTO:
    return TripDetailDTO(
        id=trip.id,
        name=trip.name,
        booking_refs=trip.booking_refs,
        start_date=trip.start_date,
        end_date=trip.end_date,
        origin_airport=trip.origin_airport,
        destination_airport=trip.destination_airport,
        is_auto_generated=trip.is_auto_generated,
        user_id=trip.user_id,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
        image_fetched_at=trip.image_fetched_at,
        rating=trip.rating,
        note=trip.note,
        is_owner=is_owner,
        owner_username=owner_username,
        flights=flights,
        expenses_total=expenses_total,
        immich_album_id=immich_album_id,
    )
