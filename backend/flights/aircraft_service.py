"""Aircraft info lookup for a single flight (cached result + hexdb recovery,
or a live fetch via the aircraft integration) — kept out of service.py since
it's an integration-lookup concern, not flight CRUD."""

from datetime import datetime

from ..utils import calc_flight_status, now_iso
from .errors import FlightError
from .repository import FlightRepository


class FlightAircraftService:
    def __init__(self, repository: FlightRepository | None = None):
        self._repository = repository or FlightRepository()

    async def get_flight_aircraft(self, flight_id: str, user_id: int) -> dict:
        """Return cached aircraft info, or fetch from OpenSky if the flight is
        still active. Completed flights are not queried against OpenSky — the
        background aircraft sync job handles lookups while flights are airborne."""
        if not self._can_access_flight(flight_id, user_id):
            raise FlightError("Flight not found", 404)
        row = self._repository.get_aircraft_fields(flight_id)
        if row is None:
            raise FlightError("Flight not found", 404)

        if row["aircraft_fetched_at"]:
            type_name = row["aircraft_type"] or ""
            icao24 = row["aircraft_icao"] or ""

            # Recovery: if type name or registration was wiped but ICAO24 is intact, resolve it now
            registration = row["aircraft_registration"] or ""
            if (not type_name or not registration) and icao24:
                from ..integrations.aircraft.client import _fetch_type_name_from_hexdb

                type_name, _, recovered_reg = await _fetch_type_name_from_hexdb(icao24)
                if recovered_reg and not registration:
                    registration = recovered_reg
                if type_name:
                    self._repository.update_aircraft_recovery(
                        flight_id, user_id, type_name, registration, now_iso()
                    )

            return {
                "type_name": type_name,
                "icao24": icao24,
                "registration": row["aircraft_registration"] or "",
                "fetched_at": row["aircraft_fetched_at"],
            }

        # Don't hit OpenSky for completed flights — they're no longer airborne
        if row["arrival_datetime"]:
            try:
                arr = datetime.fromisoformat(row["arrival_datetime"])
                if calc_flight_status(arr) == "completed":
                    return {}
            except ValueError:
                pass

        from ..integrations.aircraft.client import get_or_fetch_aircraft

        return await get_or_fetch_aircraft(flight_id, row["flight_number"], user_id)

    def _can_access_flight(self, flight_id: str, user_id: int) -> bool:
        from ..auth import can_access_flight
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_flight(flight_id, user_id, conn)


flight_aircraft_service = FlightAircraftService()
