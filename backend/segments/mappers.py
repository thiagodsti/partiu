"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import Place, Segment
from .dto import PlaceDTO, SegmentDTO


def row_to_segment(row: sqlite3.Row) -> Segment:
    return Segment(
        id=row["id"],
        trip_id=row["trip_id"],
        type=row["type"],
        operator=row["operator"],
        number=row["number"],
        booking_reference=row["booking_reference"],
        departure=Place(
            name=row["departure_place"],
            lat=row["departure_lat"],
            lon=row["departure_lon"],
            timezone=row["departure_timezone"],
            country_code=row["departure_country"],
        ),
        departure_datetime=row["departure_datetime"],
        arrival=Place(
            name=row["arrival_place"],
            lat=row["arrival_lat"],
            lon=row["arrival_lon"],
            timezone=row["arrival_timezone"],
            country_code=row["arrival_country"],
        ),
        arrival_datetime=row["arrival_datetime"],
        seat=row["seat"],
        notes=row["notes"],
        created_by=row["created_by"],
        created_by_username=row["created_by_username"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def place_to_dto(place: Place) -> PlaceDTO:
    return PlaceDTO(
        name=place.name,
        lat=place.lat,
        lon=place.lon,
        timezone=place.timezone,
        country_code=place.country_code,
    )


def segment_to_dto(segment: Segment) -> SegmentDTO:
    return SegmentDTO(
        id=segment.id,
        trip_id=segment.trip_id,
        type=segment.type,
        operator=segment.operator,
        number=segment.number,
        booking_reference=segment.booking_reference,
        departure=place_to_dto(segment.departure),
        departure_datetime=segment.departure_datetime,
        arrival=place_to_dto(segment.arrival),
        arrival_datetime=segment.arrival_datetime,
        duration_minutes=segment.duration_minutes,
        seat=segment.seat,
        notes=segment.notes,
        created_by=segment.created_by,
        created_by_username=segment.created_by_username,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )
