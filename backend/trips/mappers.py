"""Conversions between SQL rows, domain objects and DTOs."""

import json
import sqlite3

from .domain import Trip
from .dto import TripDetailDTO, TripListItemDTO, TripPlaceDTO


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
        planned_start_date=_col(row, "planned_start_date"),
        planned_end_date=_col(row, "planned_end_date"),
        origin_airport=row["origin_airport"],
        destination_airport=row["destination_airport"],
        origin_place=_col(row, "origin_place"),
        origin_lat=_col(row, "origin_lat"),
        origin_lon=_col(row, "origin_lon"),
        origin_country=_col(row, "origin_country"),
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
    destinations: list[dict],
    is_owner: bool,
    owner_username: str | None,
    flight_count: int,
    segment_count: int,
    stay_count: int,
    car_rental_count: int,
    collaborator_count: int,
    pending_invite_count: int,
    guest_count: int,
    segment_types: list[str],
    expenses_total: dict[str, float],
    budget_amount: float | None,
    budget_currency: str | None,
    budget_spent: float | None,
    immich_album_id: str | None,
    search_index: str,
) -> TripListItemDTO:
    return TripListItemDTO(
        id=trip.id,
        name=trip.name,
        booking_refs=trip.booking_refs,
        start_date=trip.start_date,
        end_date=trip.end_date,
        planned_start_date=trip.planned_start_date,
        planned_end_date=trip.planned_end_date,
        origin_airport=trip.origin_airport,
        destination_airport=trip.destination_airport,
        origin_place=trip.origin_place,
        origin_lat=trip.origin_lat,
        origin_lon=trip.origin_lon,
        origin_country=trip.origin_country,
        destinations=[TripPlaceDTO(**place) for place in destinations],
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
        segment_count=segment_count,
        stay_count=stay_count,
        car_rental_count=car_rental_count,
        collaborator_count=collaborator_count,
        pending_invite_count=pending_invite_count,
        guest_count=guest_count,
        segment_types=segment_types,
        expenses_total=expenses_total,
        budget_amount=budget_amount,
        budget_currency=budget_currency,
        budget_spent=budget_spent,
        immich_album_id=immich_album_id,
        search_index=search_index,
    )


def trip_to_detail_dto(
    trip: Trip,
    *,
    destinations: list[dict],
    is_owner: bool,
    owner_username: str | None,
    flights: list[dict],
    expenses_total: dict[str, float],
    immich_album_id: str | None,
    collaborator_count: int = 0,
    pending_invite_count: int = 0,
    guest_count: int = 0,
) -> TripDetailDTO:
    return TripDetailDTO(
        id=trip.id,
        name=trip.name,
        booking_refs=trip.booking_refs,
        start_date=trip.start_date,
        end_date=trip.end_date,
        planned_start_date=trip.planned_start_date,
        planned_end_date=trip.planned_end_date,
        origin_airport=trip.origin_airport,
        destination_airport=trip.destination_airport,
        origin_place=trip.origin_place,
        origin_lat=trip.origin_lat,
        origin_lon=trip.origin_lon,
        origin_country=trip.origin_country,
        destinations=[TripPlaceDTO(**place) for place in destinations],
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
        collaborator_count=collaborator_count,
        pending_invite_count=pending_invite_count,
        guest_count=guest_count,
    )


def _col(row: sqlite3.Row, name: str):
    """Read a column that may not exist on rows from older queries.

    `row_to_trip` is fed by several SELECTs, not all of which list every column;
    a missing one is None rather than an IndexError.
    """
    try:
        return row[name]
    except (IndexError, KeyError):
        return None
