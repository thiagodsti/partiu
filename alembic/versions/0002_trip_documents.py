"""Add trip_documents table for user-uploaded files (PDFs, images).

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trip_documents (
            id TEXT PRIMARY KEY,
            trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            page_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trip_documents_trip_id ON trip_documents(trip_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS trip_documents")
