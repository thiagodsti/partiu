"""
Trip documents API — user-uploaded files (PDFs, images) attached to a trip.

  GET    /api/trips/{trip_id}/documents          — list documents for a trip
  POST   /api/trips/{trip_id}/documents          — upload a document
  GET    /api/documents/{doc_id}/view            — render as image (?page=N for PDFs)
  DELETE /api/documents/{doc_id}                 — delete
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response

from ..auth import get_current_user
from ..database import db_conn, db_write
from ..shares import can_access_trip, is_trip_owner
from ..utils import now_iso

router = APIRouter(tags=["trip-documents"])

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}
_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


def _get_storage_dir() -> Path:
    from ..config import settings

    doc_dir = Path(settings.DB_PATH).parent / "trip_documents"
    doc_dir.mkdir(parents=True, exist_ok=True)
    return doc_dir


def _safe_file_path(file_path: str) -> Path:
    """Resolve path and verify it stays within the storage directory."""
    storage_dir = _get_storage_dir().resolve()
    resolved = Path(file_path).resolve()
    if not str(resolved).startswith(str(storage_dir) + "/"):
        raise HTTPException(status_code=403, detail="Access denied")
    return resolved


def _trip_belongs_to_user(trip_id: str, user_id: int) -> bool:
    """Read access: owner or accepted collaborator."""
    with db_conn() as conn:
        return can_access_trip(trip_id, user_id, conn)


def _trip_owned_by_user(trip_id: str, user_id: int) -> bool:
    """Write access: owner only."""
    with db_conn() as conn:
        return is_trip_owner(trip_id, user_id, conn)


def _doc_readable_by_user(doc_id: str, user_id: int) -> dict | None:
    """Read access: owner or accepted collaborator."""
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM trip_documents WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            return None
        if not can_access_trip(row["trip_id"], user_id, conn):
            return None
    return dict(row)


def _doc_owned_by_user(doc_id: str, user_id: int) -> dict | None:
    """Write access: owner only."""
    with db_conn() as conn:
        row = conn.execute(
            """SELECT d.* FROM trip_documents d
               JOIN trips t ON t.id = d.trip_id
               WHERE d.id = ? AND t.user_id = ?""",
            (doc_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def _pdf_page_count(file_path: str) -> int:
    try:
        import fitz

        doc = fitz.open(file_path)
        count = len(doc)
        doc.close()
        return max(count, 1)
    except Exception:
        return 1


def _render_pdf_page(file_path: str, page_num: int) -> bytes:
    import fitz

    doc = fitz.open(file_path)
    page_num = max(0, min(page_num, len(doc) - 1))
    page = doc[page_num]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    data = pix.tobytes("png")
    doc.close()
    return data


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("/api/trips/{trip_id}/documents")
def list_documents(trip_id: str, user: dict = Depends(get_current_user)):
    if not _trip_belongs_to_user(trip_id, user["id"]):
        raise HTTPException(status_code=404, detail="Trip not found")

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trip_documents WHERE trip_id = ? ORDER BY created_at ASC",
            (trip_id,),
        ).fetchall()

    return [
        {
            "id": r["id"],
            "trip_id": r["trip_id"],
            "filename": r["filename"],
            "mime_type": r["mime_type"],
            "file_size": r["file_size"],
            "page_count": r["page_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post("/api/trips/{trip_id}/documents", status_code=201)
async def upload_document(
    trip_id: str,
    file: UploadFile,
    user: dict = Depends(get_current_user),
):
    if not _trip_belongs_to_user(trip_id, user["id"]):
        raise HTTPException(status_code=404, detail="Trip not found")

    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {content_type}. Use PDF or an image.",
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")
    if len(data) < 10:
        raise HTTPException(status_code=422, detail="File is empty or too small")

    doc_id = str(uuid.uuid4())
    ext = _EXTENSIONS.get(content_type, ".bin")
    file_path = str(_get_storage_dir() / f"{doc_id}{ext}")
    Path(file_path).write_bytes(data)

    page_count = _pdf_page_count(file_path) if content_type == "application/pdf" else 1
    original_name = file.filename or f"document{ext}"

    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_documents
               (id, trip_id, filename, file_path, mime_type, file_size, page_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                doc_id,
                trip_id,
                original_name,
                file_path,
                content_type,
                len(data),
                page_count,
                now_iso(),
            ),
        )

    return {"id": doc_id, "page_count": page_count}


# ---------------------------------------------------------------------------
# View (always served as an image — PDFs are rendered per-page)
# ---------------------------------------------------------------------------


@router.get("/api/documents/{doc_id}/view")
def view_document(
    doc_id: str,
    page: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
):
    doc = _doc_readable_by_user(doc_id, user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = _safe_file_path(doc["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    if doc["mime_type"] == "application/pdf":
        image_bytes = _render_pdf_page(str(file_path), page)
        return Response(content=image_bytes, media_type="image/png")

    # For images, serve the file directly with the correct content type
    suffix = file_path.suffix.lower()
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        suffix, "image/png"
    )
    return Response(content=file_path.read_bytes(), media_type=media_type)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: dict = Depends(get_current_user)):
    doc = _doc_owned_by_user(doc_id, user["id"])
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    raw_path = doc.get("file_path")

    with db_write() as conn:
        conn.execute("DELETE FROM trip_documents WHERE id = ?", (doc_id,))

    if raw_path:
        try:
            _safe_file_path(raw_path).unlink(missing_ok=True)
        except (OSError, HTTPException):
            pass
