"""Travel statistics endpoint."""

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from . import stats_service
from .dto import TravelStatsDTO
from .mappers import stats_to_dto

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=TravelStatsDTO)
def get_stats(year: int | None = None, user: dict = Depends(get_current_user)):
    """Return travel statistics for the current user, optionally filtered by year."""
    stats = stats_service.compute_stats(user["id"], year)
    return stats_to_dto(stats)
