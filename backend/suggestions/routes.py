"""AI place suggestions API.

GET  /api/suggestions/status                 — is it on, and the caller's preference
PUT  /api/suggestions/prefs                  — {use_history}
POST /api/trips/{trip_id}/plan/suggestions   — places for a stop or a day
POST /api/trips/{trip_id}/plan/suggestions/locate — one picked place on the map
POST /api/trips/{trip_id}/plan/arrange       — a proposed order and times for a day

Suggestions are never written to the plan here: the traveller adds the ones
they want through the planner's own item API.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..integrations.ai.client import AiBadAnswerError, AiNotConfiguredError, AiUnreachableError
from .dto import (
    ArrangedItemDTO,
    ArrangeRequestDTO,
    ArrangeResponseDTO,
    LocatedDTO,
    LocateRequestDTO,
    StayPointDTO,
    SuggestionDTO,
    SuggestionsPrefsDTO,
    SuggestionsStatusDTO,
    SuggestRequestDTO,
    SuggestResponseDTO,
)
from .service import (
    DailyLimitError,
    NothingToArrangeError,
    PlaceUnknownError,
    SuggestionsUnavailableError,
    TripNotFoundError,
    suggestions_service,
)

router = APIRouter(tags=["suggestions"])


@router.get("/api/suggestions/status", response_model=SuggestionsStatusDTO)
def get_status(user: dict = Depends(get_current_user)):
    return SuggestionsStatusDTO(**suggestions_service.status(user["id"]))


@router.put("/api/suggestions/prefs", response_model=SuggestionsPrefsDTO)
def set_prefs(body: SuggestionsPrefsDTO, user: dict = Depends(get_current_user)):
    suggestions_service.set_use_history(user["id"], body.use_history)
    return body


@router.post("/api/trips/{trip_id}/plan/suggestions", response_model=SuggestResponseDTO)
def suggest(trip_id: str, body: SuggestRequestDTO, user: dict = Depends(get_current_user)):
    try:
        result = suggestions_service.suggest(
            trip_id,
            user["id"],
            stop_id=body.stop_id,
            day=body.date,
            interests=list(body.interests),
            wish=body.wish,
            exclude=body.exclude,
        )
    except SuggestionsUnavailableError:
        raise HTTPException(status_code=404, detail="ai_not_configured")
    except TripNotFoundError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except PlaceUnknownError:
        raise HTTPException(status_code=422, detail="place_unknown")
    except DailyLimitError:
        raise HTTPException(status_code=429, detail="daily_limit")
    except AiNotConfiguredError:
        raise HTTPException(status_code=503, detail="ai_misconfigured")
    except AiUnreachableError:
        raise HTTPException(status_code=503, detail="ai_unreachable")
    except AiBadAnswerError:
        raise HTTPException(status_code=502, detail="ai_bad_answer")
    return SuggestResponseDTO(
        city=result["city"],
        day=result["day"],
        stay=StayPointDTO(**result["stay"]) if result.get("stay") else None,
        stay_without_pin=result.get("stay_without_pin"),
        suggestions=[SuggestionDTO(**s) for s in result["suggestions"]],
        unverified=result["unverified"],
    )


@router.post("/api/trips/{trip_id}/plan/suggestions/locate", response_model=LocatedDTO | None)
def locate(trip_id: str, body: LocateRequestDTO, user: dict = Depends(get_current_user)):
    """The map position of one suggestion being added; ``null`` when the map
    does not know it — the caller adds it without a pin."""
    try:
        found = suggestions_service.locate(
            trip_id, user["id"], stop_id=body.stop_id, day=body.date, name=body.name
        )
    except SuggestionsUnavailableError:
        raise HTTPException(status_code=404, detail="ai_not_configured")
    except TripNotFoundError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except PlaceUnknownError:
        raise HTTPException(status_code=422, detail="place_unknown")
    return LocatedDTO(**found) if found else None


@router.post("/api/trips/{trip_id}/plan/arrange", response_model=ArrangeResponseDTO)
def arrange(trip_id: str, body: ArrangeRequestDTO, user: dict = Depends(get_current_user)):
    """A proposal only: the planner applies it when the traveller accepts."""
    try:
        result = suggestions_service.arrange(
            trip_id, user["id"], day=body.date, busy=[b.model_dump() for b in body.busy]
        )
    except SuggestionsUnavailableError:
        raise HTTPException(status_code=404, detail="ai_not_configured")
    except TripNotFoundError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except PlaceUnknownError:
        raise HTTPException(status_code=422, detail="place_unknown")
    except NothingToArrangeError:
        raise HTTPException(status_code=422, detail="nothing_to_arrange")
    except DailyLimitError:
        raise HTTPException(status_code=429, detail="daily_limit")
    except AiNotConfiguredError:
        raise HTTPException(status_code=503, detail="ai_misconfigured")
    except AiUnreachableError:
        raise HTTPException(status_code=503, detail="ai_unreachable")
    except AiBadAnswerError:
        raise HTTPException(status_code=502, detail="ai_bad_answer")
    return ArrangeResponseDTO(
        day=result["day"],
        items=[ArrangedItemDTO(**i) for i in result["items"]],
        tip=result["tip"],
    )
