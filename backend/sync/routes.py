"""
Sync control routes.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile

from ..auth import get_current_user
from ..limiter import limiter
from . import sync_service
from .dto import SyncStatusDTO, TriggerResponseDTO, UploadEmlResponseDTO
from .mappers import sync_status_to_dto
from .service import MAX_EML_FILES, MAX_EML_SIZE, EmlParseError

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status", response_model=SyncStatusDTO)
def get_sync_status(user: dict = Depends(get_current_user)):
    """Return the current sync state for this user."""
    return sync_status_to_dto(sync_service.get_status(user["id"]))


@router.post("/now", response_model=TriggerResponseDTO)
@limiter.limit("5/minute")
def sync_now(
    request: Request, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)
):
    """Trigger an immediate email sync (runs in background)."""
    if not sync_service.try_acquire_lock():
        return TriggerResponseDTO(status="already_running", message="Sync is already in progress")

    background_tasks.add_task(sync_service.run_sync_for_user, user["id"])
    return TriggerResponseDTO(status="started", message="Sync started in background")


@router.post("/regroup", response_model=TriggerResponseDTO)
def regroup(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Re-run grouping on all flights (re-creates auto-generated trips)."""
    from ..activity.service import activity_service

    activity_service.record(user["id"], "trips.regrouped")
    background_tasks.add_task(sync_service.trigger_regroup, user["id"])
    return TriggerResponseDTO(status="started", message="Regrouping started in background")


@router.post("/full-sync", response_model=TriggerResponseDTO)
def full_sync(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """
    Clear last_synced_at *and the processed-mail ledger*, then re-sync from the
    full first_sync_days window. Existing flights are kept: duplicates are
    refused by the unique key on the source mail, not by the ledger.
    """
    if not sync_service.try_acquire_lock():
        return TriggerResponseDTO(status="already_running", message="Sync is already in progress")

    sync_service.reset_last_synced(user["id"])
    from ..activity.service import activity_service

    activity_service.record(user["id"], "sync.full")
    background_tasks.add_task(sync_service.run_sync_for_user, user["id"])
    return TriggerResponseDTO(status="started", message="Full sync started in background")


@router.post("/upload-eml", response_model=UploadEmlResponseDTO)
@limiter.limit("20/minute")
async def upload_eml(
    request: Request,
    files: list[UploadFile],
    user: dict = Depends(get_current_user),
):
    """Parse one or more uploaded .eml files and import flights from them."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > MAX_EML_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files (max {MAX_EML_FILES})")

    raw_files: list[tuple[str | None, bytes]] = []
    for upload in files:
        raw = await upload.read()
        if len(raw) > MAX_EML_SIZE:
            raise HTTPException(
                status_code=400, detail=f"File {upload.filename!r} exceeds 10 MB limit"
            )
        raw_files.append((upload.filename, raw))

    try:
        result = sync_service.import_eml_files(raw_files, user_id=user["id"])
    except EmlParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UploadEmlResponseDTO(**result)
