"""Use cases for trips: listing (with owner/flight-count/expense/search-index
enrichment), CRUD, merge, flight assignment, and rating/note.

iCalendar export, destination-image fetching, and Immich album orchestration
are separate concerns — see ical_service.py, image_service.py, and
immich_service.py."""

import json
import unicodedata
import uuid
from collections.abc import Mapping

from ..integrations.wikipedia.client import trip_image_path
from .domain import Trip
from .dto import PlaceFieldsDTO
from .errors import TripError
from .repository import TripRepository


def _norm(s: str) -> str:
    """Strip diacritics and lowercase for accent-insensitive search."""
    return unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode("ascii").lower()


class TripListItem:
    """Assembled (Trip + computed extras) ready for mapping to a DTO."""

    def __init__(self, trip: Trip, is_owner: bool):
        self.trip = trip
        self.is_owner = is_owner
        self.owner_username: str | None = None
        self.flight_count = 0
        self.segment_count = 0
        self.stay_count = 0
        self.car_rental_count = 0
        self.segment_types: list[str] = []
        self.expenses_total: dict[str, float] = {}
        self.immich_album_id: str | None = None
        self.destinations: list[dict] = []
        self.budget_amount: float | None = None
        self.budget_currency: str | None = None
        self.budget_spent: float | None = None
        self.search_index = ""


class TripService:
    def __init__(self, repository: TripRepository | None = None):
        self._repository = repository or TripRepository()

    # -- List / get ------------------------------------------------------------

    def list_trips(self, user_id: int) -> list[TripListItem]:
        """Return all trips ordered by start_date (owned + accepted shared)."""
        owned = self._repository.list_owned(user_id)
        shared = self._repository.list_shared_accepted(user_id)

        seen_ids: set[str] = set()
        items: list[TripListItem] = []
        for trip in owned + shared:
            if trip.id in seen_ids:
                continue
            seen_ids.add(trip.id)
            items.append(TripListItem(trip, is_owner=(trip.user_id == user_id)))

        items.sort(key=lambda i: i.trip.start_date or "")

        self._attach_extras(items, user_id)
        return items

    def _attach_extras(self, items: list[TripListItem], user_id: int) -> None:
        """Mutate each item to add flight_count, segment_count, stay_count,
        car_rental_count,
        segment_types, owner_username, expenses_total, immich_album_id,
        destinations, and search_index."""
        trip_ids = [i.trip.id for i in items]
        if not trip_ids:
            return

        flight_counts = self._repository.get_flight_counts(trip_ids)
        segment_counts = self._repository.get_segment_counts(trip_ids)
        stay_counts = self._repository.get_stay_counts(trip_ids)
        car_rental_counts = self._repository.get_car_rental_counts(trip_ids)
        segment_types = self._repository.get_segment_types(trip_ids)
        for item in items:
            item.flight_count = flight_counts.get(item.trip.id, 0)
            item.segment_count = segment_counts.get(item.trip.id, 0)
            item.stay_count = stay_counts.get(item.trip.id, 0)
            item.car_rental_count = car_rental_counts.get(item.trip.id, 0)
            item.segment_types = segment_types.get(item.trip.id, [])

        owner_ids = list(
            {i.trip.user_id for i in items if not i.is_owner and i.trip.user_id is not None}
        )
        usernames = self._repository.get_usernames(owner_ids) if owner_ids else {}
        for item in items:
            owner_id = item.trip.user_id
            item.owner_username = (
                None if item.is_owner or owner_id is None else usernames.get(owner_id)
            )

        expense_totals = self._repository.get_expenses_totals(trip_ids)
        for item in items:
            item.expenses_total = expense_totals.get(item.trip.id, {})

        album_ids = self._repository.get_immich_album_ids(trip_ids, user_id)
        for item in items:
            item.immich_album_id = album_ids.get(item.trip.id)

        # Build a pre-normalised search index: trip name + booking refs + all flight
        # cities, country codes, IATA codes, airline names, and flight numbers.
        # Booking references come from the legs as well as the trip: the trip-level
        # list is written by auto-grouping, while a hand-added flight or ground leg
        # carries its own, and both have to be findable by the same search.
        # One read for every card's budget rather than one per card.
        from ..expenses.service import expense_service

        budgets = expense_service.budgets_for_trips(user_id, trip_ids)
        for item in items:
            status = budgets.get(item.trip.id)
            if status and status.budget:
                item.budget_amount = status.budget.amount
                item.budget_currency = status.budget.currency
                item.budget_spent = status.spent

        destinations = self._repository.list_destinations(trip_ids)
        for item in items:
            item.destinations = destinations.get(item.trip.id, [])

        search_rows = self._repository.get_search_index_rows(trip_ids)
        segment_refs = self._repository.get_segment_booking_refs(trip_ids)
        for item in items:
            fi = search_rows.get(item.trip.id)
            parts = [
                item.trip.name or "",
                " ".join(item.trip.booking_refs),
                segment_refs.get(item.trip.id, ""),
                item.trip.origin_place or "",
                " ".join(place["name"] for place in item.destinations),
            ]
            if fi:
                parts += [
                    fi[c] or ""
                    for c in (
                        "dep_iatas",
                        "arr_iatas",
                        "dep_cities",
                        "arr_cities",
                        "dep_countries",
                        "arr_countries",
                        "airlines",
                        "flight_nums",
                        "booking_refs",
                    )
                ]
            item.search_index = _norm(" ".join(filter(None, parts)))

    def get_trip(
        self, trip_id: str, user_id: int
    ) -> tuple[Trip, bool, str | None, list[dict], dict, str | None, list[dict]]:
        """Return a single trip with its flights.

        Returns (trip, is_owner, owner_username, flights, expenses_total,
        immich_album_id, destinations).
        """
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)

        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripError("Trip not found", 404)

        is_owner = trip.user_id == user_id
        owner_username = None if is_owner else self._repository.get_owner_username(trip.user_id)
        flights = self._repository.get_flights_for_trip(trip_id)
        expenses_total = self._repository.get_expenses_total(trip_id)
        immich_album_id = self._repository.get_immich_album_id(trip_id, user_id)
        destinations = self._repository.list_destinations([trip_id]).get(trip_id, [])

        return (
            trip,
            is_owner,
            owner_username,
            flights,
            expenses_total,
            immich_album_id,
            destinations,
        )

    # -- Create / update / delete --------------------------------------------

    def create_trip(
        self,
        user_id: int,
        name: str,
        booking_refs: list[str],
        start_date: str,
        end_date: str,
        origin_airport: str,
        destination_airport: str,
        places: dict | None = None,
        destinations: list | None = None,
    ) -> str:
        trip_id = str(uuid.uuid4())
        now = _now_iso()
        self._repository.create(
            trip_id,
            name,
            json.dumps(booking_refs),
            start_date,
            end_date,
            origin_airport,
            destination_airport,
            user_id,
            now,
        )
        if places:
            self._repository.update(trip_id, user_id, {**places, "updated_at": now})
        if destinations:
            self._repository.set_destinations(trip_id, self.destination_rows(destinations), now)
        return trip_id

    @staticmethod
    def destination_rows(places) -> list[dict]:
        """Normalise the destination list to the rows the table takes.

        Blank names are dropped rather than stored: an empty row is what a
        half-filled form leaves behind, and a nameless destination would count
        as a place the trip goes to.
        """
        rows: list[dict] = []
        for place in places or []:
            data = dict(place) if isinstance(place, Mapping) else place.model_dump()
            name = str(data.get("name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "country_code": (data.get("country_code") or None),
                }
            )
        return rows

    @staticmethod
    def place_columns(prefix: str, place: PlaceFieldsDTO | Mapping[str, object]) -> dict:
        """Flatten a place into its `<prefix>_*` columns.

        Takes the DTO *or* a plain mapping, because the two routes hand it over
        differently: create passes the `PlaceFieldsDTO` straight through, while
        update goes via `body.model_dump()`, which turns nested models into
        dicts. Assuming the object form crashed every trip edit with a 500 —
        the edit form always sends both places, so it was not only date changes.
        """
        data = dict(place) if isinstance(place, Mapping) else place.model_dump()
        name = str(data.get("name") or "").strip()
        if not name:
            return {
                f"{prefix}_place": None,
                f"{prefix}_lat": None,
                f"{prefix}_lon": None,
                f"{prefix}_country": None,
            }
        return {
            f"{prefix}_place": name,
            f"{prefix}_lat": data.get("lat"),
            f"{prefix}_lon": data.get("lon"),
            f"{prefix}_country": (data.get("country_code") or None),
        }

    def update_trip(self, trip_id: str, user_id: int, updates: dict) -> None:
        """``updates`` maps DTO field name to new value; ``booking_refs`` (a list)
        is JSON-encoded before being handed to the repository."""
        if self._repository.get_owned(trip_id, user_id) is None:
            raise TripError("Trip not found", 404)

        column_updates = dict(updates)
        # The form's date fields edit the *declared* span; `start_date`/`end_date`
        # are derived and are rewritten by `recompute_span` from the contents
        # unioned with this pair. Writing both keeps a trip with no legs showing
        # the dates it was just given.
        for field, planned in (
            ("start_date", "planned_start_date"),
            ("end_date", "planned_end_date"),
        ):
            if field in column_updates:
                column_updates[planned] = column_updates[field] or None
        # `origin` arrives as a nested place object; the table stores it
        # flattened, and the nested key is not a column.
        place = column_updates.pop("origin", None)
        if place is not None:
            column_updates.update(self.place_columns("origin", place))

        # Destinations are rows, not columns — written after the trip row itself.
        destinations = column_updates.pop("destinations", None)
        if "booking_refs" in column_updates:
            column_updates["booking_refs"] = json.dumps(column_updates["booking_refs"])

        if destinations is not None:
            self._repository.set_destinations(
                trip_id, self.destination_rows(destinations), _now_iso()
            )

        column_updates["updated_at"] = _now_iso()
        self._repository.update(trip_id, user_id, column_updates)

        # Editing the declared span has to re-derive the real one: shortening a
        # trip's dates is the only way its span ever shrinks.
        if "planned_start_date" in column_updates or "planned_end_date" in column_updates:
            self._repository.recompute_span(trip_id, _now_iso())

    def delete_trip(self, trip_id: str, user_id: int) -> None:
        """Move the trip and everything on it to the trash.

        The live rows are deleted as before — the trash keeps a snapshot, and
        the cover image stays on disk until the trash entry is purged. See
        `trash.service` for why the delete still has to be a real delete.
        """
        if not self._is_owner(trip_id, user_id):
            raise TripError("Trip not found", 404)

        from ..trash.service import trash_service

        trash_service.trash_trip(trip_id, user_id)

    def merge_trip(self, trip_id: str, target_trip_id: str, user_id: int) -> None:
        if trip_id == target_trip_id:
            raise TripError("Cannot merge a trip into itself", 400)
        if not self._is_owner(trip_id, user_id):
            raise TripError("Trip not found", 404)
        if not self._can_access(target_trip_id, user_id):
            raise TripError("Target trip not found", 404)

        now = _now_iso()
        source = self._repository.get_by_id(trip_id)
        target = self._repository.get_by_id(target_trip_id)
        self._repository.merge_trips(trip_id, target_trip_id, user_id, now)
        from ..activity.service import activity_service

        activity_service.record(
            user_id,
            "trips.merged",
            entity_type="trip",
            entity_id=target_trip_id,
            label=target.name if target else target_trip_id,
            details={"source_trip_id": trip_id, "source_name": source.name if source else None},
        )

        webp = trip_image_path(trip_id)
        webp.unlink(missing_ok=True)
        webp.with_suffix(".jpg").unlink(missing_ok=True)

    # -- Flight assignment -----------------------------------------------------

    def add_flight_to_trip(self, trip_id: str, flight_id: str, user_id: int) -> None:
        if not self._repository.trip_owned_exists(trip_id, user_id):
            raise TripError("Trip not found", 404)
        if not self._repository.flight_owned_exists(flight_id, user_id):
            raise TripError("Flight not found", 404)
        self._repository.assign_flight(flight_id, trip_id, user_id, _now_iso())

    def remove_flight_from_trip(self, trip_id: str, flight_id: str, user_id: int) -> None:
        self._repository.unassign_flight(flight_id, trip_id, user_id, _now_iso())

    # -- Rating / note ---------------------------------------------------------

    def set_rating(self, trip_id: str, user_id: int, rating: float | None) -> None:
        if rating is not None and rating not in [x / 2 for x in range(1, 11)]:
            raise TripError("Rating must be a multiple of 0.5 between 0.5 and 5", 422)
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)
        self._repository.set_rating(trip_id, rating, _now_iso())

    def set_note(self, trip_id: str, user_id: int, note: str | None) -> None:
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)
        self._repository.set_note(trip_id, note, _now_iso())

    # -- Access helpers -------------------------------------------------------

    def _can_access(self, trip_id: str, user_id: int) -> bool:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)

    def _is_owner(self, trip_id: str, user_id: int) -> bool:
        from ..auth import is_trip_owner
        from ..database import db_conn

        with db_conn() as conn:
            return is_trip_owner(trip_id, user_id, conn)


def _now_iso() -> str:
    from ..utils import now_iso

    return now_iso()


trip_service = TripService()
