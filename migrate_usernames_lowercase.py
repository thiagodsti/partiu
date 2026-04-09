"""
One-time migration: lowercase all existing usernames.

Detects conflicts (e.g. 'Thiago' and 'thiago' both exist) and reports them
without making any changes, so you can resolve them manually first.

Usage:
    uv run python migrate_usernames_lowercase.py [--db PATH] [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Lowercase all usernames in the DB.")
    parser.add_argument("--db", default="data/partiu.db", help="Path to SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying them")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT id, username FROM users ORDER BY id").fetchall()

    if not rows:
        print("No users found. Nothing to do.")
        conn.close()
        return

    # Detect conflicts: two usernames that would collide after lowercasing
    seen: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        key = row["username"].lower()
        seen.setdefault(key, []).append((row["id"], row["username"]))

    conflicts = {k: v for k, v in seen.items() if len(v) > 1}
    if conflicts:
        print("CONFLICT: the following usernames would collide after lowercasing:")
        for lower, entries in conflicts.items():
            entries_str = ", ".join(f"id={uid} '{uname}'" for uid, uname in entries)
            print(f"  '{lower}' ← {entries_str}")
        print("\nResolve conflicts manually before running this migration.")
        conn.close()
        sys.exit(1)

    # Show planned changes
    changes = [
        (row["id"], row["username"], row["username"].lower())
        for row in rows
        if row["username"] != row["username"].lower()
    ]

    if not changes:
        print("All usernames are already lowercase. Nothing to do.")
        conn.close()
        return

    print(f"{'DRY RUN — ' if args.dry_run else ''}Usernames to update ({len(changes)}):")
    for uid, old, new in changes:
        print(f"  id={uid}: '{old}' → '{new}'")

    if args.dry_run:
        print("\nDry run complete. No changes made.")
        conn.close()
        return

    # Apply
    try:
        with conn:
            for uid, _old, new in changes:
                conn.execute("UPDATE users SET username = ? WHERE id = ?", (new, uid))
        print(f"\nDone. Updated {len(changes)} username(s).")
    except Exception as e:
        print(f"ERROR during update: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
