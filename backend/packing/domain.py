"""Domain object for the packing-list feature."""

from dataclasses import dataclass


@dataclass
class PackingItem:
    id: str
    trip_id: str
    text: str
    checked: bool
    sort_order: int
    created_by: int | None
    created_at: str
