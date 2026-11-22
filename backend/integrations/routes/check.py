"""Turn an LLM-read leg around when its route is the exact reverse of the known one.

The one correction made, and the only one this data is trusted for. Measured
on the 40-mail eval sample (eval_llm_corpus) with qwen3:4b-instruct: all five
inverted legs were the exact reverse of the known route and were fixed, and no
leg that was right came back as reversed. Every other outcome leaves the leg
alone:

- route matches: nothing to do;
- route differs: airlines reuse flight numbers, so a leg that disagrees with
  volunteer data is not wrong for that reason (8 of 81 corpus legs differ, all
  of them right);
- callsign unknown (12 of 81, mostly LATAM) or no data loaded: nothing to say.
"""

from __future__ import annotations

import logging
import re

from ...database import db_conn

logger = logging.getLogger(__name__)

_FLIGHT = re.compile(r"([A-Z0-9]{2})0*(\d{1,4}[A-Z]?)")


def known_routes(flight_number: str) -> list[list[str]]:
    """Routes for a flight number as IATA airport codes, one list per airline mapping.

    The callsign is the airline's ICAO code plus the number without leading
    zeros (AZ2058 → ITY2058, AY0806 → FIN806).
    """
    m = _FLIGHT.fullmatch((flight_number or "").upper().replace(" ", ""))
    if not m:
        return []
    code, number = m.groups()
    try:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT r.airports FROM airline_icao a"
                " JOIN flight_routes r ON r.callsign = a.icao || ?"
                " WHERE a.iata = ?",
                (number, code),
            ).fetchall()
            if not rows:
                return []
            icao_codes = {c for (airports,) in rows for c in airports.split("-")}
            placeholders = ",".join("?" * len(icao_codes))
            to_iata = dict(
                conn.execute(
                    f"SELECT icao_code, iata_code FROM airports WHERE icao_code IN ({placeholders})",
                    sorted(icao_codes),
                ).fetchall()
            )
    except Exception as e:  # noqa: BLE001 - tables missing or empty: no opinion
        logger.debug("Flight routes: lookup failed for %s (%s)", flight_number, e)
        return []
    return [[to_iata.get(c, "") for c in airports.split("-")] for (airports,) in rows]


def is_reversed(flight_number: str, dep: str, arr: str) -> bool:
    """True when arr→dep is a leg of a known route and dep→arr is not."""
    forward = backward = False
    for route in known_routes(flight_number):
        pairs = set(zip(route, route[1:], strict=False))
        forward |= (dep, arr) in pairs
        backward |= (arr, dep) in pairs
    return backward and not forward


def fix_reversed_route(flight: dict) -> dict:
    """Swap the airports of a normalised flight dict whose route is reversed.

    Times stay: the model reads the departure time correctly and only mixes
    up which airport it belongs to. Terminals and gates swap with the airports.
    """
    dep = flight.get("departure_airport") or ""
    arr = flight.get("arrival_airport") or ""
    if not dep or not arr or not is_reversed(flight.get("flight_number") or "", dep, arr):
        return flight
    logger.info(
        "Flight routes: %s read as %s→%s, known as %s→%s; turned around",
        flight.get("flight_number"),
        dep,
        arr,
        arr,
        dep,
    )
    fixed = dict(flight)
    for a, b in (
        ("departure_airport", "arrival_airport"),
        ("departure_terminal", "arrival_terminal"),
        ("departure_gate", "arrival_gate"),
    ):
        fixed[a], fixed[b] = flight.get(b, ""), flight.get(a, "")
    return fixed
