"""Known flight routes from Virtual Radar Server's standing data.

The LLM fallback reads the right airports but, on some layouts, in the wrong
order: Azul's "Seu voo para Florianópolis" heading above "VCP … FLN" makes a 4B
model answer FLN→VCP every time, ITA's "FCO LIN" comes back LIN→FCO, and an
inverted leg passes every validation gate. A table of which airports each
callsign flies, in order, catches exactly that case.

Source: https://github.com/vradarserver/standing-data, CC0, built from routes
that Virtual Radar Server users submit (about 630,000 callsigns). It is
volunteer data, so it can be stale: airlines reuse flight numbers for other
routes over the years (Finnair's AY813 was HEL→ARN in 2024 and is HEL→BRU in
the data now). That is why the data is only ever used to **turn an exactly
reversed leg around** — never to reject a leg, add one, or change an airport
(see check.py).

The whole repository is one ~6 MB tarball; only routes/schema-01 and
airlines/schema-01 are read, straight from the gzip stream, and both tables
are replaced in one transaction, so a failed or partial download leaves the
previous data in place. Nothing here runs during an email sync.
"""

from __future__ import annotations

import csv
import io
import logging
import tarfile
import urllib.request
from collections.abc import Iterator

from ...database import db_conn, db_write, set_global_setting
from ...utils import now_iso

logger = logging.getLogger(__name__)

TARBALL_URL = "https://codeload.github.com/vradarserver/standing-data/tar.gz/refs/heads/main"
UPDATED_AT_KEY = "flight_routes_updated_at"
_TIMEOUT = 120


def _csv_rows(tar: tarfile.TarFile, member: tarfile.TarInfo) -> Iterator[dict]:
    raw = tar.extractfile(member)
    if raw is None:
        return
    # utf-8-sig: the files open with a byte-order mark
    yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def parse_tarball(data: bytes) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (routes, airlines) from a standing-data tarball.

    routes: (callsign, "ICAO-ICAO[-ICAO…]"); airlines: (iata, icao) pairs.
    """
    routes: list[tuple[str, str]] = []
    airlines: set[tuple[str, str]] = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".csv"):
                continue
            parts = member.name.split("/")
            if "routes" in parts and "schema-01" in parts:
                for row in _csv_rows(tar, member):
                    callsign = (row.get("Callsign") or "").strip().upper()
                    airports = (row.get("AirportCodes") or "").strip().upper()
                    if callsign and "-" in airports:
                        routes.append((callsign, airports))
            elif parts[-1] == "airlines.csv" and "schema-01" in parts:
                for row in _csv_rows(tar, member):
                    iata = (row.get("IATA") or "").strip().upper()
                    icao = (row.get("ICAO") or "").strip().upper()
                    if len(iata) == 2 and len(icao) == 3:
                        airlines.add((iata, icao))
    return routes, sorted(airlines)


def replace_tables(routes: list[tuple[str, str]], airlines: list[tuple[str, str]]) -> None:
    """Swap both tables for the new data in a single transaction."""
    with db_write() as conn:
        conn.execute("DELETE FROM flight_routes")
        conn.execute("DELETE FROM airline_icao")
        conn.executemany(
            "INSERT OR REPLACE INTO flight_routes (callsign, airports) VALUES (?, ?)", routes
        )
        conn.executemany("INSERT OR IGNORE INTO airline_icao (iata, icao) VALUES (?, ?)", airlines)


def route_count() -> int:
    try:
        with db_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM flight_routes").fetchone()[0]
    except Exception:  # noqa: BLE001 - table missing on an unmigrated DB
        return 0


def refresh_routes(url: str = TARBALL_URL) -> int:
    """Download the standing data and replace the route tables.

    Returns the number of routes stored, or 0 when the download or the parse
    failed, in which case the previous data is left untouched.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "partiu"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read()
        routes, airlines = parse_tarball(data)
    except Exception as e:  # noqa: BLE001 - an outage must never break anything
        logger.warning("Flight routes: download failed, keeping the previous data (%s)", e)
        return 0
    if not routes or not airlines:
        logger.warning("Flight routes: download had no routes, keeping the previous data")
        return 0
    replace_tables(routes, airlines)
    set_global_setting(UPDATED_AT_KEY, now_iso())
    logger.info("Flight routes: stored %d routes, %d airline codes", len(routes), len(airlines))
    return len(routes)
