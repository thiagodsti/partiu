"""Flights feature: CRUD, listing/pagination, and ungrouping a flight into its
own solo trip (service.py); CSV export (export_service.py) and aircraft
lookup (aircraft_service.py) are separate concerns, each its own singleton."""

from .aircraft_service import FlightAircraftService, flight_aircraft_service
from .export_service import FlightExportService, flight_export_service
from .service import FlightService, flight_service

__all__ = [
    "FlightAircraftService",
    "FlightExportService",
    "FlightService",
    "flight_aircraft_service",
    "flight_export_service",
    "flight_service",
]
