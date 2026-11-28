"""Request and response shapes for AI place suggestions."""

from typing import Literal

from pydantic import BaseModel, Field

Interest = Literal["sights", "food", "museums", "nature", "nightlife", "kids", "budget"]


class SuggestRequestDTO(BaseModel):
    # One of the two says where: a route stop (the whole stay in that city), or
    # a day (the city slept in that night). Neither: the trip's first destination.
    stop_id: str | None = None
    date: str | None = None
    interests: list[Interest] = Field(default_factory=list, max_length=7)
    wish: str | None = Field(default=None, max_length=200)
    # Titles already shown in this panel, so "more" brings new ones.
    exclude: list[str] = Field(default_factory=list, max_length=60)


class SuggestionDTO(BaseModel):
    title: str
    why: str
    category: str
    best_time: str
    # From the place's Wikipedia article, when it has one near the city: its
    # photo and its position. Without one, the place is looked up on the map
    # only when it is added (POST …/suggestions/locate).
    on_wikipedia: bool = False
    image_url: str | None = None
    image_page: str | None = None
    lat: float | None = None
    lon: float | None = None
    # The map's name when it is in another script, from the up-front lookup a
    # self-hosted Photon allows.
    local_name: str | None = None


class LocateRequestDTO(BaseModel):
    stop_id: str | None = None
    date: str | None = None
    name: str = Field(min_length=1, max_length=120)


class LocatedDTO(BaseModel):
    place_name: str
    # The map's name when it is in another script (OSM in China, Japan…).
    local_name: str | None = None
    address: str
    lat: float
    lon: float


class StayPointDTO(BaseModel):
    name: str
    lat: float
    lon: float


class SuggestResponseDTO(BaseModel):
    city: str
    day: str | None
    # Where the traveller sleeps, when that stay is booked and on the map: the
    # panel shows each card's distance from it.
    stay: StayPointDTO | None = None
    # A stay booked there that has no position, by name.
    stay_without_pin: str | None = None
    suggestions: list[SuggestionDTO]
    # Kept for older clients; nothing is dropped unchecked any more.
    unverified: int = 0


class SuggestionsStatusDTO(BaseModel):
    available: bool
    use_history: bool
    daily_limit: int
    used_today: int


class SuggestionsPrefsDTO(BaseModel):
    use_history: bool


_TIME = r"^\d{2}:\d{2}$"


class BusyDTO(BaseModel):
    """A fixed part of the day the plan must leave free (a flight, a train, a
    check-in), as the planner shows it: local times at the place."""

    start: str = Field(pattern=_TIME)
    end: str | None = Field(default=None, pattern=_TIME)
    label: str = Field(min_length=1, max_length=120)


class ArrangeRequestDTO(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    busy: list[BusyDTO] = Field(default_factory=list, max_length=12)


class ArrangedItemDTO(BaseModel):
    id: str
    title: str
    time: str | None
    # The time the item has now, so the preview can show what changes.
    current_time: str | None
    # A booked item with a time keeps it: the booking decides, not the model.
    fixed: bool = False


class ArrangeResponseDTO(BaseModel):
    day: str
    items: list[ArrangedItemDTO]
    tip: str | None = None
