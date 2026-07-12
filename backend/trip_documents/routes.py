"""
Trip documents API — user-uploaded files (PDFs, images) attached to a trip.

  GET    /api/trips/{trip_id}/documents          — list documents for a trip
  POST   /api/trips/{trip_id}/documents          — upload a document
  GET    /api/documents/{doc_id}/view            — render as image (?page=N for PDFs)
  DELETE /api/documents/{doc_id}                 — delete
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response

from ..auth import get_current_user
from . import trip_document_service
from .dto import TripDocumentDTO, UploadResponseDTO
from .errors import (
    AccessDeniedError,
    DocumentNotFoundError,
    FileNotFoundOnDiskError,
    FileTooLargeError,
    FileTooSmallError,
    TripAccessError,
    UnsupportedFileTypeError,
)
from .mappers import document_to_dto

router = APIRouter(tags=["trip-documents"])


@router.get("/api/trips/{trip_id}/documents", response_model=list[TripDocumentDTO])
def list_documents(trip_id: str, user: dict = Depends(get_current_user)):
    try:
        docs = trip_document_service.list_for_trip(trip_id, user["id"])
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    return [document_to_dto(d) for d in docs]


@router.post("/api/trips/{trip_id}/documents", status_code=201, response_model=UploadResponseDTO)
async def upload_document(
    trip_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
):
    try:
        content_type = trip_document_service.check_upload_allowed(
            trip_id, user["id"], file.content_type
        )
    except TripAccessError:
        raise HTTPException(status_code=404, detail="Trip not found")
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    data = await file.read()
    try:
        doc = trip_document_service.save_upload(trip_id, content_type, file.filename, data)
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except FileTooSmallError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return UploadResponseDTO(id=doc.id, page_count=doc.page_count)


@router.get("/api/documents/{doc_id}/view")
def view_document(
    doc_id: str,
    page: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    try:
        image_bytes, media_type = trip_document_service.get_view(doc_id, user["id"], page)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    except FileNotFoundOnDiskError:
        raise HTTPException(status_code=404, detail="File not found on disk")
    except AccessDeniedError:
        raise HTTPException(status_code=403, detail="Access denied")
    return Response(content=image_bytes, media_type=media_type)


@router.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: dict = Depends(get_current_user)):
    try:
        trip_document_service.delete(doc_id, user["id"])
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    return None
