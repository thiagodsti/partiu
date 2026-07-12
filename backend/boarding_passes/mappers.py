"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import BoardingPass, TripBoardingPass
from .dto import BoardingPassDTO, TripBoardingPassDTO


def row_to_boarding_pass(row: sqlite3.Row) -> BoardingPass:
    return BoardingPass(
        id=row["id"],
        flight_id=row["flight_id"],
        passenger_name=row["passenger_name"],
        seat=row["seat"],
        image_path=row["image_path"],
        source_email_id=row["source_email_id"],
        source_page=row["source_page"],
        created_at=row["created_at"],
    )


def row_to_trip_boarding_pass(row: sqlite3.Row) -> TripBoardingPass:
    return TripBoardingPass(
        id=row["id"],
        flight_id=row["flight_id"],
        passenger_name=row["passenger_name"],
        seat=row["seat"],
        source_page=row["source_page"],
        created_at=row["created_at"],
        flight_number=row["flight_number"],
        departure_airport=row["departure_airport"],
        arrival_airport=row["arrival_airport"],
    )


def boarding_pass_to_dto(bp: BoardingPass) -> BoardingPassDTO:
    return BoardingPassDTO(
        id=bp.id,
        flight_id=bp.flight_id,
        passenger_name=bp.passenger_name,
        seat=bp.seat,
        source_page=bp.source_page,
        created_at=bp.created_at,
    )


def trip_boarding_pass_to_dto(bp: TripBoardingPass) -> TripBoardingPassDTO:
    return TripBoardingPassDTO(
        id=bp.id,
        flight_id=bp.flight_id,
        passenger_name=bp.passenger_name,
        seat=bp.seat,
        source_page=bp.source_page,
        created_at=bp.created_at,
        flight_number=bp.flight_number,
        departure_airport=bp.departure_airport,
        arrival_airport=bp.arrival_airport,
    )
