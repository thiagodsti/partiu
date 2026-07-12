"""Airport lookup routes."""

from fastapi import APIRouter, HTTPException, Request

from ..limiter import limiter
from .repository import AirportRepository

router = APIRouter(prefix="/api/airports", tags=["airports"])
_repository = AirportRepository()


@router.get("/search")
@limiter.limit("60/minute")
def search_airports(request: Request, q: str = "", limit: int = 10):
    """Search airports by IATA code prefix, name, or city (max 10 results)."""
    q = q.strip()
    if not q:
        return []
    return _repository.search(q, limit)


@router.get("/{iata}")
def get_airport(iata: str):
    """Return airport info including coordinates."""
    airport = _repository.get_by_iata(iata)
    if not airport:
        raise HTTPException(status_code=404, detail="Airport not found")
    return airport
