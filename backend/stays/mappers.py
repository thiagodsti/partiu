"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import Stay, StayPlace
from .dto import StayDTO, StayPlaceDTO


def row_to_stay(row: sqlite3.Row) -> Stay:
    return Stay(
        id=row["id"],
        trip_id=row["trip_id"],
        kind=row["kind"],
        place=StayPlace(
            name=row["name"],
            address=row["address"],
            lat=row["lat"],
            lon=row["lon"],
            timezone=row["timezone"],
            country_code=row["country"],
        ),
        check_in_datetime=row["check_in_datetime"],
        check_in_date=row["check_in_date"],
        check_out_datetime=row["check_out_datetime"],
        check_out_date=row["check_out_date"],
        booking_reference=row["booking_reference"],
        confirmation=row["confirmation"],
        contact=row["contact"],
        room_type=row["room_type"],
        guests=row["guests"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_by_username=row["created_by_username"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def place_to_dto(place: StayPlace) -> StayPlaceDTO:
    return StayPlaceDTO(
        name=place.name,
        address=place.address,
        lat=place.lat,
        lon=place.lon,
        timezone=place.timezone,
        country_code=place.country_code,
    )


def stay_to_dto(stay: Stay) -> StayDTO:
    return StayDTO(
        id=stay.id,
        trip_id=stay.trip_id,
        kind=stay.kind,
        place=place_to_dto(stay.place),
        check_in_datetime=stay.check_in_datetime,
        check_in_date=stay.check_in_date,
        check_out_datetime=stay.check_out_datetime,
        check_out_date=stay.check_out_date,
        nights=stay.nights,
        booking_reference=stay.booking_reference,
        confirmation=stay.confirmation,
        contact=stay.contact,
        room_type=stay.room_type,
        guests=stay.guests,
        notes=stay.notes,
        created_by=stay.created_by,
        created_by_username=stay.created_by_username,
        created_at=stay.created_at,
        updated_at=stay.updated_at,
    )
