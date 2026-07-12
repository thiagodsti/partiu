"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import PackingItem
from .dto import PackingItemDTO


def row_to_item(row: sqlite3.Row) -> PackingItem:
    return PackingItem(
        id=row["id"],
        trip_id=row["trip_id"],
        text=row["text"],
        checked=bool(row["checked"]),
        sort_order=row["sort_order"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def item_to_dto(item: PackingItem) -> PackingItemDTO:
    return PackingItemDTO(
        id=item.id,
        trip_id=item.trip_id,
        text=item.text,
        checked=item.checked,
        sort_order=item.sort_order,
        created_by=item.created_by,
        created_at=item.created_at,
    )
