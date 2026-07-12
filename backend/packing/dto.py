"""Request/response DTOs for the packing-list HTTP API (routes.py)."""

from pydantic import BaseModel, Field


class PackingItemDTO(BaseModel):
    id: str
    trip_id: str
    text: str
    checked: bool
    sort_order: int
    created_by: int | None
    created_at: str


class CreatePackingItemDTO(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class UpdatePackingItemDTO(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    checked: bool | None = None


class CreateItemResponseDTO(BaseModel):
    id: str
    ok: bool


class OkDTO(BaseModel):
    ok: bool
