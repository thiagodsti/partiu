"""Tests for trip documents upload, view, and delete API."""

import io
import uuid
from pathlib import Path

import pytest


def _make_trip(client, name="Iceland Trip"):
    r = client.post("/api/trips", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_second_user_client(api_app, admin_client):
    """Create a second (non-admin) user and return a logged-in TestClient for them."""
    from fastapi.testclient import TestClient

    admin_client.post(
        "/api/users",
        json={"username": "user2", "password": "password123", "is_admin": False},
    )
    c2 = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
    c2.post("/api/auth/login", json={"username": "user2", "password": "password123"})
    return c2


def _minimal_png() -> bytes:
    """1×1 transparent PNG."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


def _minimal_pdf() -> bytes:
    """Minimal single-page PDF created with pymupdf."""
    import fitz

    doc = fitz.open()
    doc.new_page(width=200, height=200)
    return doc.tobytes()


class TestListDocuments:
    def test_empty_list(self, auth_client):
        trip_id = _make_trip(auth_client)
        r = auth_client.get(f"/api/trips/{trip_id}/documents")
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_auth(self, client):
        r = client.get("/api/trips/fake-id/documents")
        assert r.status_code == 401

    def test_trip_not_found(self, auth_client):
        r = auth_client.get(f"/api/trips/{uuid.uuid4()}/documents")
        assert r.status_code == 404


class TestUploadDocument:
    def test_upload_png(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("ticket.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        assert r.status_code == 201
        assert "id" in r.json()

    def test_upload_pdf(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("bus.pdf", io.BytesIO(_minimal_pdf()), "application/pdf")},
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["page_count"] >= 1

    def test_upload_appears_in_list(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("ticket.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        docs = auth_client.get(f"/api/trips/{trip_id}/documents").json()
        assert len(docs) == 1
        assert docs[0]["filename"] == "ticket.png"
        assert docs[0]["mime_type"] == "image/png"

    def test_unsupported_type_rejected(self, auth_client):
        trip_id = _make_trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
        )
        assert r.status_code == 422

    def test_empty_file_rejected(self, auth_client):
        trip_id = _make_trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
        )
        assert r.status_code == 422


class TestViewDocument:
    def test_view_image(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("ticket.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        doc_id = up.json()["id"]
        r = auth_client.get(f"/api/documents/{doc_id}/view")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")

    def test_view_pdf_renders_as_image(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("bus.pdf", io.BytesIO(_minimal_pdf()), "application/pdf")},
        )
        doc_id = up.json()["id"]
        r = auth_client.get(f"/api/documents/{doc_id}/view")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"

    def test_view_not_found(self, auth_client):
        r = auth_client.get(f"/api/documents/{uuid.uuid4()}/view")
        assert r.status_code == 404


class TestDeleteDocument:
    def test_delete_removes_from_list(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("ticket.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        doc_id = up.json()["id"]

        r = auth_client.delete(f"/api/documents/{doc_id}")
        assert r.status_code == 204

        docs = auth_client.get(f"/api/trips/{trip_id}/documents").json()
        assert docs == []

    def test_delete_removes_file_from_disk(self, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("ticket.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        doc_id = up.json()["id"]

        # Find the saved file
        saved_files = list(tmp_path.glob(f"{doc_id}*"))
        assert len(saved_files) == 1

        auth_client.delete(f"/api/documents/{doc_id}")
        assert not saved_files[0].exists()

    def test_delete_not_found(self, auth_client):
        r = auth_client.delete(f"/api/documents/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_cannot_access_without_auth(self, auth_client, tmp_path, monkeypatch, client):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("t.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        doc_id = up.json()["id"]

        # Unauthenticated client should be denied
        r = client.delete(f"/api/documents/{doc_id}")
        assert r.status_code == 401


class TestDocumentSecurity:
    """Verify that users can only access their own trips' documents."""

    def test_unauthenticated_cannot_upload(self, client):
        r = client.post(
            f"/api/trips/{uuid.uuid4()}/documents",
            files={"file": ("t.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        assert r.status_code == 401

    def test_unauthenticated_cannot_list(self, client):
        r = client.get(f"/api/trips/{uuid.uuid4()}/documents")
        assert r.status_code == 401

    def test_unauthenticated_cannot_view(self, client):
        r = client.get(f"/api/documents/{uuid.uuid4()}/view")
        assert r.status_code == 401

    def test_unauthenticated_cannot_delete(self, client):
        r = client.delete(f"/api/documents/{uuid.uuid4()}")
        assert r.status_code == 401

    def test_user_cannot_upload_to_other_users_trip(self, api_app, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        # Admin (user A) owns this trip
        trip_id = _make_trip(auth_client)

        # User B tries to upload to it
        c2 = _make_second_user_client(api_app, auth_client)
        r = c2.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("t.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        assert r.status_code == 404

    def test_user_cannot_list_other_users_trip_documents(self, api_app, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)

        c2 = _make_second_user_client(api_app, auth_client)
        r = c2.get(f"/api/trips/{trip_id}/documents")
        assert r.status_code == 404

    def test_user_cannot_view_other_users_document(self, api_app, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("t.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        doc_id = up.json()["id"]

        c2 = _make_second_user_client(api_app, auth_client)
        r = c2.get(f"/api/documents/{doc_id}/view")
        assert r.status_code == 404

    def test_user_cannot_delete_other_users_document(self, api_app, auth_client, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "backend.routes.trip_documents._get_storage_dir", lambda: tmp_path
        )
        trip_id = _make_trip(auth_client)
        up = auth_client.post(
            f"/api/trips/{trip_id}/documents",
            files={"file": ("t.png", io.BytesIO(_minimal_png()), "image/png")},
        )
        doc_id = up.json()["id"]

        c2 = _make_second_user_client(api_app, auth_client)
        r = c2.delete(f"/api/documents/{doc_id}")
        assert r.status_code == 404
