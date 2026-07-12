"""Tests for backend.trip_documents.service (access checks + upload validation rules)."""

import itertools
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def _seed_user(db_path: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _seed_trip(db_path: str, user_id: int) -> str:
    import sqlite3
    import uuid

    trip_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO trips (id, user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (trip_id, user_id, "Test Trip", now, now),
    )
    conn.commit()
    conn.close()
    return trip_id


def _seed_share(db_path: str, trip_id: str, user_id: int, status: str = "accepted") -> None:
    import sqlite3

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO trip_shares (trip_id, user_id, invited_by, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (trip_id, user_id, user_id, status, now, now),
    )
    conn.commit()
    conn.close()


class TestListForTrip:
    def test_raises_when_no_access(self, test_db):
        from backend.trip_documents.service import TripAccessError, TripDocumentService

        service = TripDocumentService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.list_for_trip(trip_id, other_id)


class TestCheckUploadAllowed:
    def test_raises_when_no_access(self, test_db):
        from backend.trip_documents.service import TripAccessError, TripDocumentService

        service = TripDocumentService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)

        with pytest.raises(TripAccessError):
            service.check_upload_allowed(trip_id, other_id, "image/png")

    def test_rejects_bad_content_type(self, test_db):
        from backend.trip_documents.service import TripDocumentService, UnsupportedFileTypeError

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(UnsupportedFileTypeError):
            service.check_upload_allowed(trip_id, user_id, "text/csv")

    def test_normalizes_content_type_with_charset(self, test_db):
        from backend.trip_documents.service import TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        assert (
            service.check_upload_allowed(trip_id, user_id, "image/png; charset=binary")
            == "image/png"
        )

    def test_allows_accepted_collaborator(self, test_db):
        """Upload uses read access, not owner-only — a collaborator can upload too."""
        from backend.trip_documents.service import TripDocumentService

        service = TripDocumentService()
        owner_id = _seed_user(test_db)
        collab_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_share(test_db, trip_id, collab_id, status="accepted")

        service.check_upload_allowed(trip_id, collab_id, "image/png")  # should not raise


class TestSaveUpload:
    def test_rejects_too_small(self, test_db):
        from backend.trip_documents.service import FileTooSmallError, TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(FileTooSmallError):
            service.save_upload(trip_id, "image/png", "a.png", b"x")

    def test_rejects_too_large(self, test_db):
        from backend.trip_documents.service import FileTooLargeError, TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        with pytest.raises(FileTooLargeError):
            service.save_upload(trip_id, "image/png", "a.png", b"x" * (20 * 1024 * 1024 + 1))

    def test_succeeds(self, test_db):
        from backend.trip_documents.service import TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        doc = service.save_upload(trip_id, "image/png", "a.png", _PNG_BYTES)
        items = service.list_for_trip(trip_id, user_id)
        assert len(items) == 1
        assert items[0].id == doc.id


class TestGetView:
    def test_raises_not_found_for_unknown_id(self, test_db):
        from backend.trip_documents.service import DocumentNotFoundError, TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        with pytest.raises(DocumentNotFoundError):
            service.get_view("nonexistent-id", user_id, 0)

    def test_raises_not_found_when_no_access(self, test_db):
        from backend.trip_documents.service import DocumentNotFoundError, TripDocumentService

        service = TripDocumentService()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        doc = service.save_upload(trip_id, "image/png", "a.png", _PNG_BYTES)

        with pytest.raises(DocumentNotFoundError):
            service.get_view(doc.id, other_id, 0)

    def test_returns_image_bytes_and_media_type(self, test_db):
        from backend.trip_documents.service import TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        doc = service.save_upload(trip_id, "image/png", "a.png", _PNG_BYTES)

        image_bytes, media_type = service.get_view(doc.id, user_id, 0)
        assert image_bytes == _PNG_BYTES
        assert media_type == "image/png"


class TestDelete:
    def test_raises_not_found_for_unknown_id(self, test_db):
        from backend.trip_documents.service import DocumentNotFoundError, TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        with pytest.raises(DocumentNotFoundError):
            service.delete("nonexistent-id", user_id)

    def test_raises_not_found_when_not_owner(self, test_db):
        from backend.trip_documents.service import DocumentNotFoundError, TripDocumentService

        service = TripDocumentService()
        owner_id = _seed_user(test_db)
        collab_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        _seed_share(test_db, trip_id, collab_id, status="accepted")
        doc = service.save_upload(trip_id, "image/png", "a.png", _PNG_BYTES)

        with pytest.raises(DocumentNotFoundError):
            service.delete(doc.id, collab_id)

    def test_deletes_row_and_file(self, test_db):
        from pathlib import Path

        from backend.trip_documents.service import TripDocumentService

        service = TripDocumentService()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        doc = service.save_upload(trip_id, "image/png", "a.png", _PNG_BYTES)
        file_path = Path(doc.file_path)
        assert file_path.exists()

        service.delete(doc.id, user_id)
        assert service.list_for_trip(trip_id, user_id) == []
        assert not file_path.exists()
