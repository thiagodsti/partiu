#!/usr/bin/env python3
"""
Helper script to load airports from ourairports.com CSV into the database.

Usage:
    1. Download airports.csv from https://ourairports.com/data/airports.csv
    2. Place it in the data/ directory
    3. Run: python load_airports.py

Or with a custom path:
    python load_airports.py /path/to/airports.csv
"""

import sys
import os

# Allow running from project root without installing as a package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path


def main():
    csv_path = None

    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = Path(__file__).parent / 'data' / 'airports.csv'

    if not csv_path.exists():
        print(f"ERROR: airports.csv not found at {csv_path}")
        print()
        print("Download it from:")
        print("  https://ourairports.com/data/airports.csv")
        print()
        print("Then place it in the data/ directory or provide the path as an argument:")
        print("  python load_airports.py /path/to/airports.csv")
        sys.exit(1)

    print(f"Loading airports from {csv_path}...")

    from backend.database import init_database, load_airports_if_empty, db_write, db_conn

    init_database()

    # Force reload even if table is populated
    with db_write() as conn:
        conn.execute('DELETE FROM airports')

    load_airports_if_empty()

    with db_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM airports').fetchone()[0]

    print(f"Done! Loaded {count:,} airports into the database.")


if __name__ == '__main__':
    main()
