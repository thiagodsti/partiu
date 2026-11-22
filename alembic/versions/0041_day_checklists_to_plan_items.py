"""Fold the day cards' checklists into the planner's items.

The trip page's day planner kept a checklist per day inside the day note's
JSON (`{"note": ..., "items": [{"text", "checked"}]}`), and the planner
(0040) keeps per-day items in `trip_plan_items`. Two lists for the same thing
meant what was added on one page never showed on the other, so the planner's
table becomes the only one: each checklist entry becomes an item on the same
day (checked = "done", otherwise "todo"), in the same order, and the note keeps
only its text. Legacy block-array notes (`[{type: "text"}, {type:
"checklist"}]`) are read the same way the frontend reads them.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-22
"""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _split(raw: str) -> tuple[str, list[dict]] | None:
    """(note text, checklist) for a JSON note, or None for plain text."""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        items = parsed.get("items") or []
        return str(parsed.get("note") or ""), items if isinstance(items, list) else []
    if isinstance(parsed, list):
        text = next((b for b in parsed if isinstance(b, dict) and b.get("type") == "text"), {})
        check = next(
            (b for b in parsed if isinstance(b, dict) and b.get("type") == "checklist"), {}
        )
        items = check.get("items") or []
        return str(text.get("value") or ""), items if isinstance(items, list) else []
    return None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, trip_id, date, content, updated_by FROM trip_day_notes")
    ).fetchall()
    now = datetime.now(UTC).isoformat()
    for row in rows:
        split = _split(row.content)
        if split is None:
            continue
        note, items = split
        entries = [i for i in items if isinstance(i, dict) and str(i.get("text") or "").strip()]
        if not entries:
            continue
        last = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(sort_order), -1) FROM trip_plan_items"
                " WHERE trip_id = :t AND date = :d"
            ),
            {"t": row.trip_id, "d": row.date},
        ).scalar()
        for n, entry in enumerate(entries, start=int(last) + 1):
            conn.execute(
                sa.text(
                    """INSERT INTO trip_plan_items (id, trip_id, date, title, status,
                           sort_order, created_by, created_at, updated_at)
                       VALUES (:id, :t, :d, :title, :status, :n, :by, :now, :now)"""
                ),
                {
                    "id": str(uuid.uuid4()),
                    "t": row.trip_id,
                    "d": row.date,
                    "title": str(entry["text"]).strip()[:300],
                    "status": "done" if entry.get("checked") else "todo",
                    "n": n,
                    "by": row.updated_by,
                    "now": now,
                },
            )
        conn.execute(
            sa.text("UPDATE trip_day_notes SET content = :c WHERE id = :id"),
            {"c": json.dumps({"note": note, "items": []}), "id": row.id},
        )


def downgrade() -> None:
    # The items stay in trip_plan_items; 0040's downgrade drops that table.
    pass
