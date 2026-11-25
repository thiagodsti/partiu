"""Email review routes: booking emails nothing could read.

GET  /api/email-review                    — the caller's pending emails (+ ai_available)
GET  /api/email-review/count              — how many are pending (the trips-list line)
POST /api/email-review/{id}/draft         — the LLM's reading of the legs (nothing saved)
POST /api/email-review/{id}/import        — create the confirmed legs as flights
POST /api/email-review/{id}/dismiss       — not a booking
POST /api/email-review/{id}/ignore-sender — dismiss and hide that sender's mail from now on
GET  /api/email-review/ignored-senders    — the senders the caller ignores (Settings)
DELETE /api/email-review/ignored-senders/{domain} — stop ignoring one
"""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..integrations.llm.parser import LlmUnreachableError
from .dto import (
    CandidateListDTO,
    CountDTO,
    DraftDTO,
    IgnoredSenderDTO,
    IgnoreResultDTO,
    ImportRequestDTO,
    ImportResultDTO,
)
from .service import CandidateNotFoundError, email_review_service

router = APIRouter(prefix="/api/email-review", tags=["email-review"])


def _not_found():
    return HTTPException(status_code=404, detail="Email not found")


@router.get("", response_model=CandidateListDTO)
def list_pending(user: dict = Depends(get_current_user)):
    from ..integrations.llm.parser import llm_available

    return {"items": email_review_service.list_pending(user["id"]), "ai_available": llm_available()}


@router.get("/count", response_model=CountDTO)
def count_pending(user: dict = Depends(get_current_user)):
    return {"count": email_review_service.count_pending(user["id"])}


@router.get("/ignored-senders", response_model=list[IgnoredSenderDTO])
def list_ignored_senders(user: dict = Depends(get_current_user)):
    return email_review_service.list_ignored_senders(user["id"])


@router.delete("/ignored-senders/{domain:path}", status_code=204)
def stop_ignoring(domain: str, user: dict = Depends(get_current_user)):
    try:
        email_review_service.stop_ignoring(user["id"], domain)
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="That sender is not ignored")


@router.post("/{candidate_id}/draft", response_model=DraftDTO)
def draft(candidate_id: str, user: dict = Depends(get_current_user)):
    try:
        return {"legs": email_review_service.draft(user["id"], candidate_id)}
    except CandidateNotFoundError:
        raise _not_found()
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LlmUnreachableError:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "ai_unreachable",
                "message": "The AI could not be reached. Check that Ollama is running, "
                "or fill in the form yourself.",
            },
        )


@router.post("/{candidate_id}/import", response_model=ImportResultDTO)
def import_legs(candidate_id: str, body: ImportRequestDTO, user: dict = Depends(get_current_user)):
    try:
        return email_review_service.import_legs(
            user["id"], candidate_id, [leg.model_dump() for leg in body.legs]
        )
    except CandidateNotFoundError:
        raise _not_found()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{candidate_id}/dismiss", status_code=204)
def dismiss(candidate_id: str, user: dict = Depends(get_current_user)):
    try:
        email_review_service.dismiss(user["id"], candidate_id)
    except CandidateNotFoundError:
        raise _not_found()


@router.post("/{candidate_id}/ignore-sender", response_model=IgnoreResultDTO)
def ignore_sender(candidate_id: str, user: dict = Depends(get_current_user)):
    try:
        return {"dismissed": email_review_service.ignore_sender(user["id"], candidate_id)}
    except CandidateNotFoundError:
        raise _not_found()
