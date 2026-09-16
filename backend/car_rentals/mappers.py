"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import CarRental, RentalPlace
from .dto import CarRentalDTO, RentalPlaceDTO


def row_to_car_rental(row: sqlite3.Row) -> CarRental:
    return CarRental(
        id=row["id"],
        trip_id=row["trip_id"],
        vendor=row["vendor"],
        pickup=RentalPlace(
            name=row["pickup_place"],
            address=row["pickup_address"],
            lat=row["pickup_lat"],
            lon=row["pickup_lon"],
            timezone=row["pickup_timezone"],
            country_code=row["pickup_country"],
        ),
        pickup_datetime=row["pickup_datetime"],
        pickup_date=row["pickup_date"],
        dropoff=RentalPlace(
            name=row["dropoff_place"],
            address=row["dropoff_address"],
            lat=row["dropoff_lat"],
            lon=row["dropoff_lon"],
            timezone=row["dropoff_timezone"],
            country_code=row["dropoff_country"],
        ),
        dropoff_datetime=row["dropoff_datetime"],
        dropoff_date=row["dropoff_date"],
        booking_reference=row["booking_reference"],
        vehicle=row["vehicle"],
        driver_name=row["driver_name"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_by_username=row["created_by_username"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def place_to_dto(place: RentalPlace) -> RentalPlaceDTO:
    return RentalPlaceDTO(
        name=place.name,
        address=place.address,
        lat=place.lat,
        lon=place.lon,
        timezone=place.timezone,
        country_code=place.country_code,
    )


def car_rental_to_dto(rental: CarRental) -> CarRentalDTO:
    return CarRentalDTO(
        id=rental.id,
        trip_id=rental.trip_id,
        vendor=rental.vendor,
        pickup=place_to_dto(rental.pickup),
        pickup_datetime=rental.pickup_datetime,
        pickup_date=rental.pickup_date,
        dropoff=place_to_dto(rental.dropoff),
        dropoff_datetime=rental.dropoff_datetime,
        dropoff_date=rental.dropoff_date,
        days=rental.days,
        is_one_way=rental.is_one_way,
        booking_reference=rental.booking_reference,
        vehicle=rental.vehicle,
        driver_name=rental.driver_name,
        notes=rental.notes,
        created_by=rental.created_by,
        created_by_username=rental.created_by_username,
        created_at=rental.created_at,
        updated_at=rental.updated_at,
    )
