"""Use cases for the trip organizer: trip access, validation, and the trip link.

**A stop is also a destination.** The organizer's route is the most precise
statement of where a trip goes, so adding a city to it also adds that city to
the trip's destinations (unless one of that name is already there), which is
what the trip card, the cover photo and the visited-countries count read.
Removing a stop does *not* remove the destination: the destination list is the
traveller's own, and may have been typed before the organizer existed.
"""

import uuid
from datetime import date

from .domain import ITEM_STATUSES, MAX_STOP_DAYS, PlanItem, PlanStop, PlanTask
from .repository import PlannerRepository


class TripAccessError(Exception):
    """The user cannot access this trip."""


class PlanRowNotFoundError(Exception):
    """The stop, item or task does not exist on this trip."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_span(start: str, end: str) -> None:
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError as exc:
        raise ValueError("Invalid date") from exc
    if days < 0:
        raise ValueError("A stop cannot end before it starts")
    if days > MAX_STOP_DAYS:
        raise ValueError(f"A stop cannot be longer than {MAX_STOP_DAYS} days")


def _check_date(value: str | None) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid date") from exc


# A planner item's photo is a suggested place's Wikipedia thumbnail. Only those
# hosts are accepted: the CSP lets the page load images from nowhere else, and
# a URL that points anywhere else would be a tracker on every plan view.
_IMAGE_PREFIXES = ("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")
_PAGE_PREFIX = "https://en.wikipedia.org/wiki/"


def _check_image(values: dict) -> None:
    url, page = values.get("image_url"), values.get("image_page")
    if url is not None and not url.startswith(_IMAGE_PREFIXES):
        raise ValueError("A photo must be a Wikimedia image")
    if page is not None and not page.startswith(_PAGE_PREFIX):
        raise ValueError("A photo's source must be a Wikipedia article")


class PlannerService:
    def __init__(self, repository: PlannerRepository | None = None):
        self._repository = repository or PlannerRepository()

    def get_plan(
        self, trip_id: str, user_id: int
    ) -> tuple[list[PlanStop], list[PlanItem], list[PlanTask]]:
        self._check_access(trip_id, user_id)
        return (
            self._repository.list_stops(trip_id),
            self._repository.list_items(trip_id),
            self._repository.list_tasks(trip_id),
        )

    # --- stops -------------------------------------------------------------
    def create_stop(self, trip_id: str, user_id: int, data: dict) -> str:
        self._check_access(trip_id, user_id)
        name = _clean(data.get("name"))
        if not name:
            raise ValueError("City name is required")
        _check_span(data["start_date"], data["end_date"])
        country = (_clean(data.get("country_code")) or "").upper() or None
        values = {**data, "name": name, "country_code": country, "notes": _clean(data.get("notes"))}
        stop_id = str(uuid.uuid4())
        self._repository.create_stop(stop_id, trip_id, user_id, values)
        self._repository.add_destination_if_missing(
            trip_id, name, data.get("lat"), data.get("lon"), country
        )
        return stop_id

    def update_stop(self, trip_id: str, stop_id: str, user_id: int, data: dict) -> None:
        self._check_access(trip_id, user_id)
        stop = self._repository.get_stop(stop_id, trip_id)
        if stop is None:
            raise PlanRowNotFoundError(stop_id)
        values = dict(data)
        if "name" in values:
            values["name"] = _clean(values["name"])
            if not values["name"]:
                raise ValueError("City name is required")
        if "notes" in values:
            values["notes"] = _clean(values["notes"])
        if "country_code" in values:
            values["country_code"] = (_clean(values["country_code"]) or "").upper() or None
        _check_span(
            values.get("start_date", stop.start_date), values.get("end_date", stop.end_date)
        )
        self._repository.update_stop(stop_id, trip_id, values)
        if values.get("name") and values["name"] != stop.name:
            self._repository.add_destination_if_missing(
                trip_id,
                values["name"],
                values.get("lat"),
                values.get("lon"),
                values.get("country_code"),
            )

    def delete_stop(self, trip_id: str, stop_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get_stop(stop_id, trip_id) is None:
            raise PlanRowNotFoundError(stop_id)
        self._repository.delete_stop(stop_id, trip_id)

    # --- items -------------------------------------------------------------
    def create_item(self, trip_id: str, user_id: int, data: dict) -> str:
        self._check_access(trip_id, user_id)
        title = _clean(data.get("title"))
        if not title:
            raise ValueError("Title is required")
        status = data.get("status") or "idea"
        if status not in ITEM_STATUSES:
            raise ValueError(f"Unsupported status: {status!r}")
        _check_date(data.get("date"))
        _check_image(data)
        item_id = str(uuid.uuid4())
        self._repository.create_item(
            item_id,
            trip_id,
            user_id,
            {**data, "title": title, "status": status, "notes": _clean(data.get("notes"))},
        )
        return item_id

    def update_item(self, trip_id: str, item_id: str, user_id: int, data: dict) -> None:
        """``data`` holds only the fields the caller sent, so a ``date`` of None
        means "move to the ideas list", not "leave alone"."""
        self._check_access(trip_id, user_id)
        if self._repository.get_item(item_id, trip_id) is None:
            raise PlanRowNotFoundError(item_id)
        values = dict(data)
        if "title" in values:
            values["title"] = _clean(values["title"])
            if not values["title"]:
                raise ValueError("Title is required")
        if "status" in values and values["status"] not in ITEM_STATUSES:
            raise ValueError(f"Unsupported status: {values['status']!r}")
        if "notes" in values:
            values["notes"] = _clean(values["notes"])
        _check_date(values.get("date"))
        _check_image(values)
        self._repository.update_item(item_id, trip_id, values)

    def delete_item(self, trip_id: str, item_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get_item(item_id, trip_id) is None:
            raise PlanRowNotFoundError(item_id)
        self._repository.delete_item(item_id, trip_id)

    # --- tasks -------------------------------------------------------------
    def create_task(self, trip_id: str, user_id: int, data: dict) -> str:
        self._check_access(trip_id, user_id)
        text = _clean(data.get("text"))
        if not text:
            raise ValueError("Task text is required")
        values = {"text": text, **self._assignee(trip_id, user_id, data)}
        task_id = str(uuid.uuid4())
        self._repository.create_task(task_id, trip_id, user_id, values)
        return task_id

    def update_task(self, trip_id: str, task_id: str, user_id: int, data: dict) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get_task(task_id, trip_id) is None:
            raise PlanRowNotFoundError(task_id)
        values: dict = {}
        if "text" in data:
            values["text"] = _clean(data["text"])
            if not values["text"]:
                raise ValueError("Task text is required")
        if data.get("done") is not None:
            values["done"] = 1 if data["done"] else 0
        if "assignee_type" in data or "assignee_id" in data:
            values.update(self._assignee(trip_id, user_id, data))
        self._repository.update_task(task_id, trip_id, values)

    def delete_task(self, trip_id: str, task_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get_task(task_id, trip_id) is None:
            raise PlanRowNotFoundError(task_id)
        self._repository.delete_task(task_id, trip_id)

    def _assignee(self, trip_id: str, user_id: int, data: dict) -> dict:
        """Resolve an assignee to the two columns, refusing anyone who is not a
        participant of this trip (the same people expenses can name)."""
        kind, ident = data.get("assignee_type"), data.get("assignee_id")
        if kind is None or ident is None:
            return {"assignee_user_id": None, "assignee_guest_id": None}
        from ..expenses.service import ExpenseService

        people = ExpenseService().list_participants_for_trip(trip_id, user_id)
        if not any(p.type == kind and p.id == ident for p in people):
            raise ValueError("Assignee is not on this trip")
        return {
            "assignee_user_id": ident if kind == "user" else None,
            "assignee_guest_id": ident if kind == "guest" else None,
        }

    def _check_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


planner_service = PlannerService()
