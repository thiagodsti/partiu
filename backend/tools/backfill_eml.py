"""
Backfill .eml files for failed emails that have no raw EML saved.

Matches failed_emails rows (where eml_path IS NULL) against the local
email_cache.json by message_id, reconstructs a synthetic EML, and updates
the DB row with the new eml_path.

Usage:
    uv run python -m backend.tools.backfill_eml
    uv run python -m backend.tools.backfill_eml --db-path data/eval.db
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill .eml files for failed emails without one.")
    p.add_argument("--db-path", default="", help="SQLite DB path (default: from DB_PATH env)")
    args = p.parse_args()

    if args.db_path:
        os.environ["DB_PATH"] = args.db_path

    from backend.config import settings
    from backend.database import db_conn, db_write
    from backend.email_cache import load_emails
    from backend.failed_email_queue import _build_synthetic_eml

    print(f"DB: {settings.DB_PATH}")

    # Load rows that have no eml_path
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, sender, subject FROM failed_emails WHERE eml_path IS NULL"
        ).fetchall()

    if not rows:
        print("No failed emails without .eml — nothing to do.")
        return

    print(f"Found {len(rows)} failed emails without .eml")

    # Index cached emails by sender+subject
    cache_emails = load_emails()
    by_sender_subject: dict[tuple, object] = {
        (e.sender or "", e.subject or ""): e for e in cache_emails
    }

    eml_dir = Path(settings.DB_PATH).parent / "failed_emails"
    eml_dir.mkdir(parents=True, exist_ok=True)

    updated = 0
    skipped = 0

    for row in rows:
        row = dict(row)
        email_msg = by_sender_subject.get((row.get("sender", ""), row.get("subject", "")))

        if not email_msg:
            print(f"  SKIP  (not in cache)  {row['sender'][:50]}  |  {row['subject'][:40]}")
            skipped += 1
            continue

        raw = _build_synthetic_eml(email_msg)
        if not raw:
            print(f"  SKIP  (build failed)  {row['subject'][:60]}")
            skipped += 1
            continue

        eml_path = str(eml_dir / f"{row['id']}.eml")
        Path(eml_path).write_bytes(raw)

        with db_write() as conn:
            conn.execute(
                "UPDATE failed_emails SET eml_path = ? WHERE id = ?",
                (eml_path, row["id"]),
            )

        print(f"  OK    {row['subject'][:60]}")
        updated += 1

    print(f"\nDone — {updated} backfilled, {skipped} skipped.")


if __name__ == "__main__":
    main()
