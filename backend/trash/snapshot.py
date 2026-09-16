"""Snapshot and restore of a row and everything reachable from it.

The graph is discovered from the schema, not from a list kept by hand: for
every table, `PRAGMA foreign_key_list` says which other table each of its
foreign keys points at, and a table is collected when it points at one already
collected. Starting from `trips`, that finds flights, boarding passes (through
flights), expenses and their participants, budgets and their members, day
notes, packing, stays, segments, rentals, documents, destinations, shares and
Immich albums — and whatever table is added next, without a change here.

Ownership keys (anything pointing at `users`) are never followed: a user is not
part of a trip. Composite keys are matched as tuples, so a `trip_budget_members`
row is matched on both of its columns.

Restore inserts in discovery order (parents first) and only the columns the
current schema still has, with INSERT OR IGNORE, so a row that has meanwhile
been re-created — a flight re-imported from the same mail after the trip was
deleted, which is exactly what the trash is for — is left alone and counted as
skipped rather than duplicated or clobbered.
"""

from __future__ import annotations

import sqlite3
from collections import OrderedDict

# Tables that describe the account, not the trip. Never followed, never
# snapshotted, even though rows in the graph point at them.
_ACCOUNT_TABLES = frozenset({"users", "sessions", "guests"})


def _foreign_keys(conn: sqlite3.Connection) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    """table -> [(referenced_table, [from_cols], [to_cols])], composites grouped."""
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    out: dict[str, list[tuple[str, list[str], list[str]]]] = {}
    for table in tables:
        groups: dict[int, tuple[str, list[str], list[str]]] = {}
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
            fk_id, ref_table, from_col, to_col = fk["id"], fk["table"], fk["from"], fk["to"]
            group = groups.setdefault(fk_id, (ref_table, [], []))
            group[1].append(from_col)
            group[2].append(to_col or "id")
        out[table] = list(groups.values())
    return out


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def collect_graph(
    conn: sqlite3.Connection, root_table: str, root_id: str, id_column: str = "id"
) -> OrderedDict[str, list[dict]]:
    """Every row reachable from the root row, keyed by table, parents first."""
    fks = _foreign_keys(conn)
    root_rows = [
        dict(r)
        for r in conn.execute(
            f"SELECT * FROM {root_table} WHERE {id_column} = ?", (root_id,)
        ).fetchall()
    ]
    graph: OrderedDict[str, list[dict]] = OrderedDict()
    graph[root_table] = root_rows
    # Breadth-first: a table joins the graph when one of its keys points at a
    # table already in it; it is then a parent for the next round.
    frontier = [root_table]
    while frontier:
        next_frontier: list[str] = []
        for parent in frontier:
            parent_rows = graph.get(parent, [])
            if not parent_rows:
                continue
            for child, child_fks in fks.items():
                if child in _ACCOUNT_TABLES or child == parent:
                    continue
                for ref_table, from_cols, to_cols in child_fks:
                    if ref_table != parent:
                        continue
                    wanted = {tuple(r.get(c) for c in to_cols) for r in parent_rows}
                    wanted.discard(tuple(None for _ in to_cols))
                    if not wanted:
                        continue
                    rows = [
                        dict(r)
                        for r in conn.execute(f"SELECT * FROM {child}").fetchall()
                        if tuple(r[c] for c in from_cols) in wanted
                    ]
                    if not rows:
                        continue
                    existing = graph.setdefault(child, [])
                    seen = {tuple(sorted(x.items())) for x in existing}
                    added = False
                    for row in rows:
                        key = tuple(sorted(row.items()))
                        if key not in seen:
                            existing.append(row)
                            seen.add(key)
                            added = True
                    if added and child not in next_frontier:
                        next_frontier.append(child)
        frontier = next_frontier
    return graph


def restore_graph(
    conn: sqlite3.Connection, graph: dict[str, list[dict]]
) -> dict[str, dict[str, int]]:
    """Re-insert a snapshot; returns {table: {"restored": n, "skipped": m}}."""
    result: dict[str, dict[str, int]] = {}
    for table, rows in graph.items():
        if not rows:
            continue
        current = _columns(conn, table)
        if not current:
            # The table itself is gone from the schema; nothing to put it back into.
            result[table] = {"restored": 0, "skipped": len(rows)}
            continue
        restored = 0
        for row in rows:
            cols = [c for c in current if c in row]
            placeholders = ", ".join("?" for _ in cols)
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )
            restored += 1 if cur.rowcount else 0
        result[table] = {"restored": restored, "skipped": len(rows) - restored}
    return result
