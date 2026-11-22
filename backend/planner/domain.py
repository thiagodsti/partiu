"""Domain objects for the trip organizer."""

from dataclasses import dataclass

# What a plan item is, in the order a plan moves through: an idea, something
# that still needs booking, something booked, something done.
ITEM_STATUSES: frozenset[str] = frozenset({"idea", "todo", "booked", "done"})

# A route stop longer than this is a mistyped date, not a stay.
MAX_STOP_DAYS = 365


@dataclass
class PlanStop:
    id: str
    trip_id: str
    name: str
    lat: float | None
    lon: float | None
    country_code: str | None
    start_date: str
    end_date: str
    notes: str | None


@dataclass
class PlanItem:
    id: str
    trip_id: str
    date: str | None
    time: str | None
    title: str
    notes: str | None
    place_name: str | None
    lat: float | None
    lon: float | None
    status: str
    sort_order: int


@dataclass
class PlanTask:
    id: str
    trip_id: str
    text: str
    done: bool
    assignee_type: str | None
    assignee_id: int | None
    sort_order: int
