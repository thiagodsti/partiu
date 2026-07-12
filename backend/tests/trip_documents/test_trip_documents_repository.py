"""Tests for backend.trip_documents.repository (raw CRUD + on-disk file storage)."""

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


class TestSave:
    def test_save_writes_file_and_row(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        doc = repo.save(
            trip_id=trip_id, filename="ticket.png", content_type="image/png", data=_PNG_BYTES
        )

        items = repo.list_for_trip(trip_id)
        assert len(items) == 1
        assert items[0].id == doc.id
        assert items[0].filename == "ticket.png"
        assert items[0].mime_type == "image/png"
        assert items[0].file_size == len(_PNG_BYTES)
        assert items[0].page_count == 1

        from pathlib import Path

        assert Path(items[0].file_path).read_bytes() == _PNG_BYTES

    def test_save_defaults_filename_when_missing(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)

        doc = repo.save(trip_id=trip_id, filename=None, content_type="image/png", data=_PNG_BYTES)
        assert doc.filename == "document.png"


class TestAccessQueries:
    def test_can_read_trip_true_for_owner(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        assert repo.can_read_trip(trip_id, user_id) is True

    def test_can_read_trip_false_for_stranger(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        assert repo.can_read_trip(trip_id, other_id) is False

    def test_get_readable_none_for_stranger(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        doc = repo.save(
            trip_id=trip_id, filename="a.png", content_type="image/png", data=_PNG_BYTES
        )

        assert repo.get_readable(doc.id, other_id) is None
        assert repo.get_readable(doc.id, owner_id) is not None

    def test_get_owned_none_for_nonowner(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        owner_id = _seed_user(test_db)
        other_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, owner_id)
        doc = repo.save(
            trip_id=trip_id, filename="a.png", content_type="image/png", data=_PNG_BYTES
        )

        assert repo.get_owned(doc.id, other_id) is None
        assert repo.get_owned(doc.id, owner_id) is not None


class TestDelete:
    def test_delete_removes_row(self, test_db):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        doc = repo.save(
            trip_id=trip_id, filename="a.png", content_type="image/png", data=_PNG_BYTES
        )

        repo.delete(doc.id)
        assert repo.list_for_trip(trip_id) == []

    def test_delete_file_removes_file(self, test_db):
        from pathlib import Path

        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        user_id = _seed_user(test_db)
        trip_id = _seed_trip(test_db, user_id)
        doc = repo.save(
            trip_id=trip_id, filename="a.png", content_type="image/png", data=_PNG_BYTES
        )
        assert Path(doc.file_path).exists()

        repo.delete_file(doc.file_path)
        assert not Path(doc.file_path).exists()


class TestSafeFilePath:
    def test_rejects_path_outside_storage_dir(self, test_db):
        from backend.trip_documents.errors import AccessDeniedError
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        with pytest.raises(AccessDeniedError):
            repo.safe_file_path("/etc/passwd")


class TestPdfHelpers:
    def test_page_count_returns_one_for_non_pdf(self, test_db, tmp_path):
        from backend.trip_documents.repository import TripDocumentRepository

        repo = TripDocumentRepository()
        bogus = tmp_path / "not-a.pdf"
        bogus.write_bytes(b"not a real pdf")
        assert repo.pdf_page_count(str(bogus)) == 1
